from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

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
from src.domain.tools.tool_call import ToolCall
from src.llm.base import LLMProvider
from src.llm.types import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
)
from src.run_events import NullRunEventSink, RunEvent, RunEventSink
from src.services.tools.tool_executor import ToolExecutor

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
    final_response: LLMResponse
    total_input_tokens: int
    total_output_tokens: int
    llm_rounds: int
    tool_rounds: int
    tool_calls: int
    events: list[dict[str, Any]] = field(default_factory=list)


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
    ) -> None:
        self._provider = provider
        self._tool_executor = tool_executor
        self._max_tool_rounds = max_tool_rounds
        self._max_total_tokens = max_total_tokens
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
            return self._execute_loop(request)
        except Exception as error:
            self._emit_event(
                {
                    "type": "run_failed",
                    "error_type": error.__class__.__name__,
                    "message": str(error),
                }
            )
            raise

    def _execute_loop(
        self,
        request: LLMRequest,
    ) -> LLMRunResult:
        messages = list(request.messages)
        total_input_tokens = 0
        total_output_tokens = 0
        llm_rounds = 0
        tool_rounds = 0
        tool_calls = 0

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
                request,
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

            tool_result_blocks: list[dict[str, object]] = []

            for tool_use in response.tool_calls:
                tool_calls += 1

                self._emit_event(
                    {
                        "type": "tool_call",
                        "round": llm_rounds,
                        "tool_call_id": tool_use.id,
                        "name": tool_use.name,
                        "input": tool_use.input,
                    }
                )

                result = self._tool_executor.execute(
                    ToolCall(
                        id=tool_use.id,
                        name=tool_use.name,
                        input=tool_use.input,
                    )
                )

                tool_result_blocks.append(
                    result.to_message_block()
                )

                tool_result_event: RunEvent = {
                    "type": "tool_result",
                    "round": llm_rounds,
                    "tool_call_id": result.tool_call_id,
                    "name": result.tool_name,
                    "success": result.success,
                    "error_code": result.error_code,
                    "duration_ms": result.metadata.get(
                        "duration_ms"
                    ),
                    "output_chars": len(result.output),
                    "truncated": result.metadata.get(
                        "truncated", False
                    ),
                    "exit_code": result.metadata.get(
                        "exit_code"
                    ),
                    "timed_out": result.metadata.get(
                        "timed_out"
                    ),
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

            messages.append(
                LLMMessage(
                    role="user",
                    content=tool_result_blocks,
                )
            )
