from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

from src.approval_application_outcome import ApprovalApplicationOutcome
from src.approval_pause import ApprovalPause
from src.context.context_usage_builder import ContextUsageBuilder
from src.context.history.apply_compaction_plan import (
    apply_compaction_plan,
)
from src.context.history.char_based_history_size_estimator import (
    CharBasedHistorySizeEstimator,
)
from src.context.history.compaction_report_builder import (
    CompactionReportBuilder,
)
from src.context.history.history_budget import HistoryBudget
from src.context.history.history_compactor import HistoryCompactor
from src.context.history.history_size_estimator import (
    HistorySizeEstimator,
)
from src.context.history.message_group_builder import (
    MessageGroupBuilder,
)
from src.context.history.rule_based_history_compactor import (
    RuleBasedHistoryCompactor,
)
from src.continuation_next_action import ContinuationNextAction
from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_result import ToolResult
from src.llm.base import LLMProvider
from src.llm.types import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
)
from src.run_continuation_checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    RunContinuationCheckpoint,
)
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)
from src.run_events import NullRunEventSink, RunEvent, RunEventSink
from src.services.tools.tool_executor import ToolExecutor
from src.tool_approval_gate import ToolApprovalGate
from src.tool_approval_gate_outcome import ToolApprovalGateOutcome

# A per-request cap on the compacted history view sent to the
# provider - deliberately well above ContextBudget's static-snapshot
# default (12_000, in src/context_builder.py) so the mandatory
# initial-task group (which embeds that static snapshot) still leaves
# room for a few rounds of tool-call history, and well below
# max_total_tokens' cumulative 100_000 ceiling. A placeholder worth
# tuning once this is exercised against real runs, not a derived
# constant.
DEFAULT_HISTORY_BUDGET = HistoryBudget(max_tokens=40_000)


class LLMRunLimitError(RuntimeError):
    pass


@dataclass(frozen=True)
class LLMRunResult:
    """final_response is LLMResponse | None (5E-5D-6C), not always a
    real LLMResponse: it is None for the two outcomes that are never
    produced by an actual provider call - a resumed continuation that
    pauses *again* on a later call in the same interrupted round (no
    fresh LLMResponse exists at all; the round that matters is the one
    already recorded in the checkpoint being resumed), and CANCEL_RUN
    (cancelled=True, nothing is ever sent to the provider on this
    path). Every terminal "the model is done" return (has_tool_calls
    is False, whether reached fresh or after a resume) still carries
    the real LLMResponse - only the two execution paths above have
    none to give, and neither of this codebase's two callers of
    final_response (LLMAgentRunExecutor._build_output/_build_summary)
    is ever reached for either path (both only run once
    waiting_for_approval is None and cancelled is False).

    cancelled (5E-5D-6C) mirrors waiting_for_approval's own
    already-established shape: a third, mutually exclusive terminal
    signal alongside "finished" (waiting_for_approval is None,
    cancelled is False) and "paused" (waiting_for_approval is not
    None) - set only by resume_from_checkpoint() consuming a CANCEL_RUN
    ApprovalApplicationOutcome, never by execute()'s fresh path (a
    fresh execution has no approval decision to cancel in the first
    place).
    """

    final_response: LLMResponse | None
    total_input_tokens: int
    total_output_tokens: int
    llm_rounds: int
    tool_rounds: int
    tool_calls: int
    events: list[dict[str, Any]] = field(default_factory=list)
    waiting_for_approval: ApprovalPause | None = None
    cancelled: bool = False


@dataclass(frozen=True)
class _ToolRoundCompleted:
    """Every ToolCall from start_index onward in one round finished
    without pausing - the shared return shape _process_tool_round()
    gives both execute()'s fresh rounds (start_index=0) and
    resume_from_checkpoint()'s continuation of an interrupted round
    (start_index=pending_tool_call_index+1), so _run_rounds() can
    append the same "one user message, all tool_result blocks in
    order" turn either way."""

    tool_calls: int
    tool_result_blocks: list[dict[str, object]]


@dataclass(frozen=True)
class _ToolRoundPaused:
    result: "LLMRunResult"


_ToolRoundOutcome = _ToolRoundCompleted | _ToolRoundPaused


class LLMRunExecutor:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        tool_executor: ToolExecutor,
        max_tool_rounds: int = 8,
        max_total_tokens: int = 100_000,
        event_sink: RunEventSink | None = None,
        debug_log_full_output: bool = False,
        history_compactor: HistoryCompactor | None = None,
        history_budget: HistoryBudget | None = None,
        size_estimator: HistorySizeEstimator | None = None,
        context_usage_builder: ContextUsageBuilder | None = None,
        compaction_report_builder: CompactionReportBuilder | None = (
            None
        ),
        approval_gate: ToolApprovalGate | None = None,
        run_id: str | None = None,
        task_id: str | None = None,
        continuation_checkpoint_repository: (
            RunContinuationCheckpointRepository | None
        ) = None,
    ) -> None:
        self._provider = provider
        self._tool_executor = tool_executor
        self._max_tool_rounds = max_tool_rounds
        self._max_total_tokens = max_total_tokens
        # approval_gate defaults to None - "no approval gate
        # configured" - so every existing caller/test that never
        # wires one gets identical behavior to before this stage
        # (5E-5D-4B): the check below is skipped entirely, and every
        # ToolCall goes straight to tool_executor.execute() exactly
        # as it always has.
        self._approval_gate = approval_gate
        self._run_id = run_id
        self._task_id = task_id
        self._continuation_checkpoint_repository = (
            continuation_checkpoint_repository
        )

        # A Run must not be reported as WAITING_FOR_APPROVAL unless
        # its continuation checkpoint was successfully persisted
        # (5E-5D-4C) - enforced here, at construction, rather than
        # lazily discovered mid-loop: if approval pausing is enabled
        # at all (approval_gate is not None), everything that pausing
        # depends on (run_id/task_id to locate the checkpoint,
        # continuation_checkpoint_repository to write it) must be
        # configured too. ToolApprovalGate.check() already validates
        # run_id is non-empty on its own (not duplicated here); this
        # only adds the two new prerequisites this stage introduces.
        if approval_gate is not None:
            if not task_id or not task_id.strip():
                raise ValueError(
                    "LLMRunExecutor requires a non-empty task_id "
                    "when approval_gate is configured"
                )

            if continuation_checkpoint_repository is None:
                raise ValueError(
                    "LLMRunExecutor requires "
                    "continuation_checkpoint_repository when "
                    "approval_gate is configured"
                )
        self._event_sink = (
            event_sink
            if event_sink is not None
            else NullRunEventSink()
        )
        self._debug_log_full_output = debug_log_full_output
        self._size_estimator = (
            size_estimator
            if size_estimator is not None
            else CharBasedHistorySizeEstimator()
        )
        self._history_compactor = (
            history_compactor
            if history_compactor is not None
            else RuleBasedHistoryCompactor(
                size_estimator=self._size_estimator
            )
        )
        self._history_budget = (
            history_budget
            if history_budget is not None
            else DEFAULT_HISTORY_BUDGET
        )
        self._context_usage_builder = (
            context_usage_builder
            if context_usage_builder is not None
            else ContextUsageBuilder(self._size_estimator)
        )
        self._compaction_report_builder = (
            compaction_report_builder
            if compaction_report_builder is not None
            else CompactionReportBuilder(self._size_estimator)
        )
        # Rebuilds the same groups history_compactor built internally,
        # purely to explain its decision - HistoryCompactor's Protocol
        # only returns a flat CompactionPlan (message indices), not
        # the group-level positions CompactionReportBuilder needs, so
        # this recomputes them independently rather than widening that
        # Protocol just for reporting.
        self._report_group_builder = MessageGroupBuilder()
        self._events: list[RunEvent] = []

    def _emit_event(self, event: RunEvent) -> None:
        self._events.append(event)
        self._event_sink.emit(event)

    def execute(
        self,
        request: LLMRequest,
    ) -> LLMRunResult:
        self._events = []

        try:
            return self._run_rounds(
                request_template=request,
                messages=list(request.messages),
                total_input_tokens=0,
                total_output_tokens=0,
                llm_rounds=0,
                tool_rounds=0,
                tool_calls=0,
            )
        except Exception as error:
            self._emit_event(
                {
                    "type": "run_failed",
                    "error_type": error.__class__.__name__,
                    "message": str(error),
                }
            )
            raise

    def resume_from_checkpoint(
        self,
        request_template: LLMRequest,
        checkpoint: RunContinuationCheckpoint,
        outcome: ApprovalApplicationOutcome,
    ) -> LLMRunResult:
        """Finishes the exact interrupted tool round checkpoint
        describes, consuming outcome for its one pending call, then
        continues the same tool-call/LLM loop execute() already
        implements (5E-5D-6C) - no second, independent execution loop:
        _run_rounds()/_process_tool_round() below are the identical
        methods execute() itself calls.

        request_template supplies the system_prompt/model/max_tokens
        a further provider call needs if this round finishes cleanly -
        these are not part of RunContinuationCheckpoint's schema (they
        are deterministic functions of the Run's task/agent/settings,
        not conversation state), so the caller rebuilds the same
        LLMRequest shape execute() would have built fresh, exactly as
        if this were the first call. request_template.messages is
        never read - checkpoint.messages is the actual history used.

        Restores every counter/budget from checkpoint rather than
        resetting any of them - llm_rounds/tool_rounds/
        cumulative_tool_calls/total_input_tokens/total_output_tokens
        all continue from exactly where they paused, and
        max_tool_rounds/max_total_tokens on *this* executor instance
        must match what was checkpointed (enforced below) so a resume
        can never silently grant a larger budget than the Run was
        originally configured with.
        """

        self._events = []

        try:
            return self._resume_rounds(
                request_template, checkpoint, outcome
            )
        except Exception as error:
            self._emit_event(
                {
                    "type": "run_failed",
                    "error_type": error.__class__.__name__,
                    "message": str(error),
                }
            )
            raise

    def _resume_rounds(
        self,
        request_template: LLMRequest,
        checkpoint: RunContinuationCheckpoint,
        outcome: ApprovalApplicationOutcome,
    ) -> LLMRunResult:
        if (
            checkpoint.task_id != self._task_id
            or checkpoint.run_id != self._run_id
        ):
            raise ValueError(
                "LLMRunExecutor.resume_from_checkpoint() checkpoint "
                f"(task_id={checkpoint.task_id!r}, "
                f"run_id={checkpoint.run_id!r}) does not match this "
                f"executor (task_id={self._task_id!r}, "
                f"run_id={self._run_id!r})"
            )

        if (
            checkpoint.max_tool_rounds != self._max_tool_rounds
            or checkpoint.max_total_tokens != self._max_total_tokens
        ):
            raise ValueError(
                "LLMRunExecutor.resume_from_checkpoint() refuses to "
                "resume with a different budget than was checkpointed "
                f"(checkpoint max_tool_rounds="
                f"{checkpoint.max_tool_rounds!r}/max_total_tokens="
                f"{checkpoint.max_total_tokens!r}, this executor "
                f"max_tool_rounds={self._max_tool_rounds!r}/"
                f"max_total_tokens={self._max_total_tokens!r})"
            )

        messages = list(checkpoint.messages)
        tool_calls_in_round = list(checkpoint.pending_round_tool_calls)
        completed_results = list(checkpoint.completed_tool_results)
        tool_result_blocks = [
            result.to_message_block() for result in completed_results
        ]
        llm_rounds = checkpoint.llm_rounds
        tool_rounds = checkpoint.tool_rounds
        tool_calls = checkpoint.cumulative_tool_calls
        total_input_tokens = checkpoint.total_input_tokens
        total_output_tokens = checkpoint.total_output_tokens
        pending_index = checkpoint.pending_tool_call_index

        if outcome.next_action is ContinuationNextAction.CANCEL_RUN:
            self._emit_event(
                {
                    "type": "run_cancelled",
                    "round": llm_rounds,
                    "tool_rounds": tool_rounds,
                    "tool_calls": tool_calls,
                    "total_input_tokens": total_input_tokens,
                    "total_output_tokens": total_output_tokens,
                }
            )

            return LLMRunResult(
                final_response=None,
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
                llm_rounds=llm_rounds,
                tool_rounds=tool_rounds,
                tool_calls=tool_calls,
                events=list(self._events),
                cancelled=True,
            )

        # EXECUTE_PENDING_TOOL (APPROVE/MODIFY) or REJECT_PENDING_TOOL -
        # either way outcome.tool_result is the real, already-produced
        # result for the pending call (ApprovalApplicationOutcome's own
        # invariant guarantees it is not None here). No ToolExecutor
        # call happens for it a second time - this is consuming a
        # result, not producing one. Only its tool_result event (plus
        # file_mutation, if applicable) is emitted; its tool_call event
        # was already emitted when this Run first paused.
        pending_result = outcome.tool_result
        assert pending_result is not None

        completed_results.append(pending_result)
        tool_result_blocks.append(pending_result.to_message_block())
        self._emit_tool_result_events(pending_result, llm_rounds)

        round_outcome = self._process_tool_round(
            tool_calls_in_round=tool_calls_in_round,
            start_index=pending_index + 1,
            messages=messages,
            completed_results=completed_results,
            tool_result_blocks=tool_result_blocks,
            llm_rounds=llm_rounds,
            tool_rounds=tool_rounds,
            tool_calls=tool_calls,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            current_response=None,
        )

        if isinstance(round_outcome, _ToolRoundPaused):
            return round_outcome.result

        messages.append(
            LLMMessage(
                role="user",
                content=round_outcome.tool_result_blocks,
            )
        )

        return self._run_rounds(
            request_template=request_template,
            messages=messages,
            total_input_tokens=total_input_tokens,
            total_output_tokens=total_output_tokens,
            llm_rounds=llm_rounds,
            tool_rounds=tool_rounds,
            tool_calls=round_outcome.tool_calls,
        )

    def _run_rounds(
        self,
        *,
        request_template: LLMRequest,
        messages: list[LLMMessage],
        total_input_tokens: int,
        total_output_tokens: int,
        llm_rounds: int,
        tool_rounds: int,
        tool_calls: int,
    ) -> LLMRunResult:
        while True:
            plan = self._history_compactor.compact(
                messages, self._history_budget
            )
            request_messages = apply_compaction_plan(messages, plan)

            report_groups = self._report_group_builder.build(messages)
            retained_set = set(plan.retained_indices)
            retained_positions = [
                position
                for position, group in enumerate(report_groups)
                if all(
                    index in retained_set for index in group.indices
                )
            ]
            compaction_report = self._compaction_report_builder.build(
                messages, report_groups, retained_positions
            )

            self._emit_event(
                {
                    "type": "compaction_report",
                    "round": llm_rounds + 1,
                    "retained_count": compaction_report.retained_count,
                    "removed_count": compaction_report.removed_count,
                    "original_tokens": (
                        compaction_report.original_tokens
                    ),
                    "retained_tokens": (
                        compaction_report.retained_tokens
                    ),
                    "retained_groups": (
                        compaction_report.retained_groups
                    ),
                    "removed_groups": compaction_report.removed_groups,
                }
            )

            current_request = replace(
                request_template,
                messages=request_messages,
                tools=self._tool_executor.get_definitions(),
            )

            breakdown = self._context_usage_builder.build(
                current_request, messages
            )

            self._emit_event(
                {
                    "type": "context_usage",
                    "round": llm_rounds + 1,
                    "system_prompt_tokens": (
                        breakdown.system_prompt_tokens
                    ),
                    "tool_definition_tokens": (
                        breakdown.tool_definition_tokens
                    ),
                    "initial_message_tokens": (
                        breakdown.initial_message_tokens
                    ),
                    "history_before_tokens": (
                        breakdown.history_before_tokens
                    ),
                    "history_after_tokens": (
                        breakdown.history_after_tokens
                    ),
                    "total_sent_tokens": breakdown.total_sent_tokens,
                }
            )

            response = self._provider.complete(current_request)
            llm_rounds += 1

            total_input_tokens += response.usage.input_tokens
            total_output_tokens += response.usage.output_tokens

            self._emit_event(
                {
                    "type": "llm_response",
                    "round": llm_rounds,
                    "stop_reason": response.stop_reason,
                    "input_tokens": response.usage.input_tokens,
                    "output_tokens": response.usage.output_tokens,
                }
            )

            if (
                total_input_tokens + total_output_tokens
                > self._max_total_tokens
            ):
                self._emit_event(
                    {
                        "type": "run_limit_exceeded",
                        "limit": "max_total_tokens",
                        "configured_limit": (
                            self._max_total_tokens
                        ),
                        "actual_value": (
                            total_input_tokens
                            + total_output_tokens
                        ),
                        "round": llm_rounds,
                    }
                )

                raise LLMRunLimitError(
                    "Maximum total token limit exceeded."
                )

            messages.append(
                LLMMessage(
                    role="assistant",
                    content=response.to_message_content(),
                )
            )

            if (
                response.stop_reason == "tool_use"
                and not response.has_tool_calls
            ):
                raise RuntimeError(
                    "Provider returned tool_use stop reason "
                    "without tool calls."
                )

            if not response.has_tool_calls:
                self._emit_event(
                    {
                        "type": "run_completed",
                        "llm_rounds": llm_rounds,
                        "tool_rounds": tool_rounds,
                        "tool_calls": tool_calls,
                        "total_input_tokens": total_input_tokens,
                        "total_output_tokens": total_output_tokens,
                        "stop_reason": response.stop_reason,
                    }
                )

                return LLMRunResult(
                    final_response=response,
                    total_input_tokens=total_input_tokens,
                    total_output_tokens=total_output_tokens,
                    llm_rounds=llm_rounds,
                    tool_rounds=tool_rounds,
                    tool_calls=tool_calls,
                    events=list(self._events),
                )

            tool_rounds += 1

            if tool_rounds > self._max_tool_rounds:
                self._emit_event(
                    {
                        "type": "run_limit_exceeded",
                        "limit": "max_tool_rounds",
                        "configured_limit": (
                            self._max_tool_rounds
                        ),
                        "actual_value": tool_rounds,
                        "round": llm_rounds,
                    }
                )

                raise LLMRunLimitError(
                    "Maximum tool rounds exceeded."
                )

            tool_calls_in_round = [
                ToolCall(
                    id=tool_use.id,
                    name=tool_use.name,
                    input=tool_use.input,
                )
                for tool_use in response.tool_calls
            ]

            round_outcome = self._process_tool_round(
                tool_calls_in_round=tool_calls_in_round,
                start_index=0,
                messages=messages,
                completed_results=[],
                tool_result_blocks=[],
                llm_rounds=llm_rounds,
                tool_rounds=tool_rounds,
                tool_calls=tool_calls,
                total_input_tokens=total_input_tokens,
                total_output_tokens=total_output_tokens,
                current_response=response,
            )

            if isinstance(round_outcome, _ToolRoundPaused):
                return round_outcome.result

            tool_calls = round_outcome.tool_calls

            messages.append(
                LLMMessage(
                    role="user",
                    content=round_outcome.tool_result_blocks,
                )
            )

    def _process_tool_round(
        self,
        *,
        tool_calls_in_round: list[ToolCall],
        start_index: int,
        messages: list[LLMMessage],
        completed_results: list[ToolResult],
        tool_result_blocks: list[dict[str, object]],
        llm_rounds: int,
        tool_rounds: int,
        tool_calls: int,
        total_input_tokens: int,
        total_output_tokens: int,
        current_response: LLMResponse | None,
    ) -> _ToolRoundOutcome:
        """Processes tool_calls_in_round[start_index:] in order -
        start_index=0 for a fresh round (execute()), or
        pending_tool_call_index+1 for the remainder of an interrupted
        round already partially consumed (resume_from_checkpoint()).
        Identical body either way: this is the one place authorization,
        ToolApprovalGate, and tool execution happen, so a later call in
        a resumed round goes through exactly the same checks a fresh
        call would (5E-5D-6C: "apply current authorization before
        approval" for every later call, not a relaxed resumed path).
        """

        for tool_index in range(start_index, len(tool_calls_in_round)):
            tool_call = tool_calls_in_round[tool_index]
            tool_calls += 1

            self._emit_event(
                {
                    "type": "tool_call",
                    "round": llm_rounds,
                    "tool_call_id": tool_call.id,
                    "name": tool_call.name,
                    "input": tool_call.input,
                }
            )

            # Authorization (ToolPolicy, inside is_authorized()) is
            # checked first and short-circuits the `and` - an
            # unauthorized tool_call never reaches approval_gate.check()
            # at all, so it can never create an ApprovalRequest; it
            # falls through to the exact same tool_executor.execute()
            # call below that already produces its own
            # UNKNOWN_TOOL/TOOL_DISABLED failure, unchanged (5E-5D-4B).
            if (
                self._approval_gate is not None
                and self._tool_executor.is_authorized(tool_call)
            ):
                gate_result = self._approval_gate.check(
                    self._run_id, tool_call
                )

                if (
                    gate_result.outcome
                    is ToolApprovalGateOutcome.WAITING_FOR_APPROVAL
                ):
                    approval_request = gate_result.approval_request
                    pause = ApprovalPause(
                        approval_id=approval_request.approval_id,
                        run_id=approval_request.run_id,
                        tool_call_id=tool_call.id,
                    )

                    # Persistence order (5E-5D-4C): ToolPolicy
                    # authorization -> ApprovalStore.create() (above,
                    # inside approval_gate.check()) -> this checkpoint
                    # -> the WAITING result returned below -> RunService
                    # persists waiting_for_approval (a later layer). A
                    # Run must not be reported WAITING unless this
                    # save() actually succeeds - it is not wrapped in a
                    # try/except here, so a failure propagates
                    # unhandled exactly like an approval_gate.check()
                    # failure already does; nothing downstream ever sees
                    # a WAITING outcome for a checkpoint that didn't
                    # persist, and the ToolCall is never executed either
                    # way. Unchanged for a later call in a resumed round
                    # (C pausing too) - a second durable pause for the
                    # same Run, overwriting checkpoint.json with C's own
                    # position.
                    checkpoint = RunContinuationCheckpoint(
                        schema_version=CHECKPOINT_SCHEMA_VERSION,
                        task_id=self._task_id,
                        run_id=self._run_id,
                        approval_id=approval_request.approval_id,
                        messages=tuple(messages),
                        pending_round_tool_calls=tuple(
                            tool_calls_in_round
                        ),
                        pending_tool_call_index=tool_index,
                        pending_tool_call_id=tool_call.id,
                        completed_tool_results=tuple(
                            completed_results
                        ),
                        llm_rounds=llm_rounds,
                        tool_rounds=tool_rounds,
                        cumulative_tool_calls=tool_calls,
                        total_input_tokens=total_input_tokens,
                        total_output_tokens=total_output_tokens,
                        max_tool_rounds=self._max_tool_rounds,
                        max_total_tokens=self._max_total_tokens,
                    )
                    self._continuation_checkpoint_repository.save(
                        checkpoint
                    )

                    self._emit_event(
                        {
                            "type": "run_waiting_for_approval",
                            "round": llm_rounds,
                            "approval_id": pause.approval_id,
                            "run_id": pause.run_id,
                            "tool_call_id": pause.tool_call_id,
                            "tool_name": tool_call.name,
                            "risk_level": (
                                approval_request.risk_level.value
                            ),
                            "input_preview": (
                                approval_request.input_preview
                            ),
                        }
                    )

                    return _ToolRoundPaused(
                        result=LLMRunResult(
                            final_response=current_response,
                            total_input_tokens=total_input_tokens,
                            total_output_tokens=total_output_tokens,
                            llm_rounds=llm_rounds,
                            tool_rounds=tool_rounds,
                            tool_calls=tool_calls,
                            events=list(self._events),
                            waiting_for_approval=pause,
                        )
                    )

            result = self._tool_executor.execute(tool_call)
            completed_results.append(result)
            tool_result_blocks.append(result.to_message_block())
            self._emit_tool_result_events(result, llm_rounds)

        return _ToolRoundCompleted(
            tool_calls=tool_calls,
            tool_result_blocks=tool_result_blocks,
        )

    def _emit_tool_result_events(
        self, result: ToolResult, llm_rounds: int
    ) -> None:
        """Shared by a freshly executed tool call and a cached
        ApprovalApplicationOutcome.tool_result being consumed on resume
        (5E-5D-6C) - the identical event shape either way, so a
        resumed B never produces a differently-shaped tool_result event
        than an ordinary tool call would have. Never called for the
        pending call's *tool_call* event, which is emitted once, at
        pause time, and never repeated here - only its tool_result (and
        optional file_mutation) are new information at resume time."""

        tool_result_event: RunEvent = {
            "type": "tool_result",
            "round": llm_rounds,
            "tool_call_id": result.tool_call_id,
            "name": result.tool_name,
            "success": result.success,
            "error_code": result.error_code,
            "duration_ms": result.metadata.get("duration_ms"),
            "output_chars": len(result.output),
            "truncated": result.metadata.get("truncated", False),
            "exit_code": result.metadata.get("exit_code"),
            "timed_out": result.metadata.get("timed_out"),
        }

        if self._debug_log_full_output:
            tool_result_event["output"] = result.output

        self._emit_event(tool_result_event)

        if "after_sha256" in result.metadata:
            self._emit_event(
                {
                    "type": "file_mutation",
                    "round": llm_rounds,
                    "tool_call_id": result.tool_call_id,
                    "operation": result.metadata.get(
                        "operation",
                        result.metadata.get("mode"),
                    ),
                    "path": result.metadata.get("path"),
                    "before_sha256": result.metadata.get(
                        "before_sha256"
                    ),
                    "after_sha256": result.metadata.get(
                        "after_sha256"
                    ),
                    "bytes_written": result.metadata.get(
                        "bytes_written"
                    ),
                }
            )
