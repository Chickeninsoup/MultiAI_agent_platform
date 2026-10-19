from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.continuation_next_action import ContinuationNextAction
from src.domain.tools.tool_result import ToolResult


@dataclass(frozen=True)
class ApprovalApplicationOutcome:
    """What actually happened when ApprovalApplicationService.apply()
    processed one resolved pending ToolCall (5E-5D-6B) - the thing
    that gets persisted inside a COMPLETED ApprovalApplicationRecord
    and returned to every caller of apply(), first-time or retried.

    next_action mirrors ApprovalContinuationPreparation.next_action
    (ContinuationNextAction) - not a new, parallel vocabulary: this is
    "what was actually done", and it is always exactly what
    preparation said to do, never a different choice made here.

    tool_result is populated for EXECUTE_PENDING_TOOL (the real
    ToolExecutor.execute() return value, including a normal *failure*
    ToolResult - this stage persists whatever ToolExecutor actually
    returned, success or not, rather than only persisting successes)
    and for REJECT_PENDING_TOOL (a synthesized, truthful rejection
    ToolResult for the pending call's id - see
    ApprovalApplicationService's own module docstring for why its text
    is fixed rather than derived from caller input). It is None for
    CANCEL_RUN - cancelling never produces a ToolResult, and nothing
    here fabricates one; a later Run orchestrator reads next_action
    directly to learn "stop, nothing executed".

    field(repr=False) on tool_result - the one field here that can
    carry a tool's raw output text (potentially echoing secrets from
    the input that produced it), for the same reason
    ApprovalContinuationPreparation.effective_tool_call is redacted:
    repr() is what debug output and test-failure messages go through.
    ToolResult itself has no such redaction today (its own repr shows
    output/metadata in full) - redacting one layer up here is the
    containing boundary's responsibility, the same choice
    ApprovalContinuationPreparation already made for ToolCall.
    """

    next_action: ContinuationNextAction
    tool_result: ToolResult | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (
            self.next_action is ContinuationNextAction.CANCEL_RUN
            and self.tool_result is not None
        ):
            raise ValueError(
                "ApprovalApplicationOutcome must not carry a "
                "tool_result when next_action is CANCEL_RUN"
            )

        if (
            self.next_action is not ContinuationNextAction.CANCEL_RUN
            and self.tool_result is None
        ):
            raise ValueError(
                "ApprovalApplicationOutcome requires a tool_result "
                f"when next_action is {self.next_action!r}"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "next_action": self.next_action.value,
            "tool_result": (
                self.tool_result.to_dict()
                if self.tool_result is not None
                else None
            ),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalApplicationOutcome":
        tool_result_data = data.get("tool_result")

        return cls(
            next_action=ContinuationNextAction(data["next_action"]),
            tool_result=(
                ToolResult.from_dict(tool_result_data)
                if tool_result_data is not None
                else None
            ),
        )
