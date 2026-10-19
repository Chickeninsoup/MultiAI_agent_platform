from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.clock import utc_now
from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_result import ToolResult
from src.llm.types import LLMMessage
from src.run_continuation_checkpoint_errors import (
    UnsupportedCheckpointVersionError,
)

CHECKPOINT_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class RunContinuationCheckpoint:
    """A durable snapshot of exactly where one Run's LLMRunExecutor
    tool-call loop paused for human approval (5E-5D-4C) - not a reuse
    of ExecutionCheckpoint (src/execution_checkpoint.py), a different
    model for a different execution stack.

    ExecutionCheckpoint tracks which TaskSteps of a multi-step
    TaskPlan have completed (task_id/plan_id-scoped, StepExecutionResult-
    shaped) - the TaskScheduler/TaskPlanExecutor orchestration stack.
    This tracks mid-round LLM tool-calling continuation state
    (run_id-scoped, LLMMessage/ToolCall/ToolResult-shaped) - the
    RunService/LLMRunExecutor stack, wired to ToolApprovalGate in
    5E-5D-4B. The two stacks share no fields today (task_id/plan_id
    vs run_id/messages/pending_round_tool_calls) because they
    describe genuinely different things; forcing one shape to cover
    both would make either a checkpoint of steps or a checkpoint of a
    conversation, never both cleanly. This is a new type that follows
    ExecutionCheckpoint/ExecutionCheckpointRepository's established
    *conventions* (frozen dataclass, tasks_dir-rooted repository,
    JsonRepository-backed, raising load()) rather than its shape.

    task_id is not in this stage's literal required-field list but is
    included anyway (5E-5D-4C) - every repository in this codebase
    needs task_id to build a deterministic path (RunRepository,
    PlanRepository, ApprovalRepository, ExecutionCheckpointRepository
    all do), and run_id alone is not guaranteed globally unique across
    tasks in this codebase (a documented, pre-existing limitation -
    see README's known-limitations section). Following that existing
    identity convention, not inventing a new one.

    messages is the exact durable history at the moment of pause,
    already including the assistant turn that introduced the current
    ToolCalls (LLMRunExecutor appends it before entering the tool-call
    loop) - "the assistant response that introduced the current
    ToolCalls" is therefore represented by messages' trailing entry
    plus pending_round_tool_calls below, not by a third, redundant
    LLMResponse-shaped field: LLMMessage.content is already the exact
    plain-dict block list a resume would resend, and LLMResponse's
    typed content blocks (LLMTextBlock/LLMThinkingBlock/LLMToolUseBlock)
    would just be that same information a second time in a different
    shape.

    pending_round_tool_calls is the ordered ToolCall list from that
    same response, kept as a separate field (not re-derived by
    re-parsing messages' last entry) because it's the structured
    working data a resume needs to actually drive continuation - which
    calls are done, which is pending, which remain - not just a
    protocol-replay artifact.

    completed_tool_results always has exactly pending_tool_call_index
    entries (enforced below) - "A must not run again, A's result must
    be preserved" for every call *before* the pending one, by
    construction. Nothing about calls *after* the pending one
    (pending_tool_call_index+1 onward in pending_round_tool_calls) has
    any result recorded anywhere - "do not fabricate ToolResults for
    the pending or later calls" holds structurally, not just by
    convention, because there is no field a fabricated one could be
    written into without violating the length invariant.

    pending_tool_call_id duplicates pending_round_tool_calls
    [pending_tool_call_index].id - not extra data, a cross-check:
    __post_init__ verifies they agree, catching a construction bug
    immediately rather than leaving two ways to find "the pending
    call" that could silently disagree.

    llm_rounds/tool_rounds/cumulative_tool_calls/total_input_tokens/
    total_output_tokens mirror LLMRunResult's own field names exactly
    (src/llm_executor.py) - the same cumulative counters, captured at
    the pause point, not re-derived or renamed. max_tool_rounds/
    max_total_tokens are the configured budget LLMRunExecutor was
    built with - carried so a future resume reconstructs the same
    limits rather than silently defaulting to different ones (a
    resumed Run silently getting a *larger* budget than it was
    originally configured with would be a quiet policy change, not a
    resume).

    approval_id references the ApprovalRequest by id only - deliberately
    not an embedded copy of it. ApprovalStore remains the single
    authoritative source for the request and its eventual resolution;
    duplicating it here would create a second place that record could
    drift from (e.g. if it's ever resolved-and-then-this-checkpoint-
    read-again).

    pending_round_tool_calls/completed_tool_results/messages are all
    field(repr=False) (5E-5D-4C) - the same reasoning ApprovalRequest.
    proposed_action already established (5E-5D-4A-1): these are the
    fields capable of carrying raw ToolCall input, tool output, or
    full conversation content, and repr() is exactly what debug
    output/logging/test-failure messages go through. Only small
    identifiers/counters are visible in repr(checkpoint).
    """

    schema_version: int
    task_id: str
    run_id: str
    approval_id: str
    messages: tuple[LLMMessage, ...] = field(repr=False)
    pending_round_tool_calls: tuple[ToolCall, ...] = field(repr=False)
    pending_tool_call_index: int
    pending_tool_call_id: str
    completed_tool_results: tuple[ToolResult, ...] = field(repr=False)
    llm_rounds: int
    tool_rounds: int
    cumulative_tool_calls: int
    total_input_tokens: int
    total_output_tokens: int
    max_tool_rounds: int
    max_total_tokens: int
    created_at: str = field(default_factory=utc_now)

    def __post_init__(self) -> None:
        if self.schema_version != CHECKPOINT_SCHEMA_VERSION:
            raise UnsupportedCheckpointVersionError(
                "Unsupported RunContinuationCheckpoint schema "
                f"version: {self.schema_version!r} (expected "
                f"{CHECKPOINT_SCHEMA_VERSION!r})"
            )

        for field_name in (
            "task_id",
            "run_id",
            "approval_id",
            "pending_tool_call_id",
        ):
            value = getattr(self, field_name)
            if not value or not value.strip():
                raise ValueError(
                    "RunContinuationCheckpoint field "
                    f"'{field_name}' must be a non-empty string"
                )

        if not (
            0
            <= self.pending_tool_call_index
            < len(self.pending_round_tool_calls)
        ):
            raise ValueError(
                "RunContinuationCheckpoint pending_tool_call_index "
                f"{self.pending_tool_call_index!r} is out of range "
                f"for {len(self.pending_round_tool_calls)} "
                "pending_round_tool_calls"
            )

        pending_call = self.pending_round_tool_calls[
            self.pending_tool_call_index
        ]

        if pending_call.id != self.pending_tool_call_id:
            raise ValueError(
                "RunContinuationCheckpoint pending_tool_call_id "
                f"{self.pending_tool_call_id!r} does not match "
                f"pending_round_tool_calls[{self.pending_tool_call_index}]"
                f".id {pending_call.id!r}"
            )

        if len(self.completed_tool_results) != (
            self.pending_tool_call_index
        ):
            raise ValueError(
                "RunContinuationCheckpoint completed_tool_results "
                f"must have exactly {self.pending_tool_call_index} "
                "entries (one per pending_round_tool_calls before "
                f"the pending index), got "
                f"{len(self.completed_tool_results)}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "task_id": self.task_id,
            "run_id": self.run_id,
            "approval_id": self.approval_id,
            "messages": [
                message.to_dict() for message in self.messages
            ],
            "pending_round_tool_calls": [
                tool_call.to_dict()
                for tool_call in self.pending_round_tool_calls
            ],
            "pending_tool_call_index": self.pending_tool_call_index,
            "pending_tool_call_id": self.pending_tool_call_id,
            "completed_tool_results": [
                result.to_dict()
                for result in self.completed_tool_results
            ],
            "llm_rounds": self.llm_rounds,
            "tool_rounds": self.tool_rounds,
            "cumulative_tool_calls": self.cumulative_tool_calls,
            "total_input_tokens": self.total_input_tokens,
            "total_output_tokens": self.total_output_tokens,
            "max_tool_rounds": self.max_tool_rounds,
            "max_total_tokens": self.max_total_tokens,
            "created_at": self.created_at,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RunContinuationCheckpoint":
        return cls(
            schema_version=data["schema_version"],
            task_id=data["task_id"],
            run_id=data["run_id"],
            approval_id=data["approval_id"],
            messages=tuple(
                LLMMessage.from_dict(message_data)
                for message_data in data["messages"]
            ),
            pending_round_tool_calls=tuple(
                ToolCall.from_dict(tool_call_data)
                for tool_call_data in data["pending_round_tool_calls"]
            ),
            pending_tool_call_index=data["pending_tool_call_index"],
            pending_tool_call_id=data["pending_tool_call_id"],
            completed_tool_results=tuple(
                ToolResult.from_dict(result_data)
                for result_data in data["completed_tool_results"]
            ),
            llm_rounds=data["llm_rounds"],
            tool_rounds=data["tool_rounds"],
            cumulative_tool_calls=data["cumulative_tool_calls"],
            total_input_tokens=data["total_input_tokens"],
            total_output_tokens=data["total_output_tokens"],
            max_tool_rounds=data["max_tool_rounds"],
            max_total_tokens=data["max_total_tokens"],
            created_at=data["created_at"],
        )
