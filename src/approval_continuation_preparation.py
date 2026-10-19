from __future__ import annotations

from dataclasses import dataclass, field

from src.approval_decision import ApprovalDecision
from src.approval_resolution import ApprovalResolution
from src.continuation_next_action import (
    ContinuationNextAction,
    next_action_for,
)
from src.domain.tools.tool_call import ToolCall
from src.run_continuation_checkpoint import RunContinuationCheckpoint


@dataclass(frozen=True)
class ApprovalContinuationPreparation:
    """A read-only description of how a paused, approval-resolved Run
    should continue (5E-5D-6A) - the output of
    ApprovalContinuationPreparationService.prepare(), consumed by a
    later execution-resume stage that has not been built yet.

    Deliberately not a second, independent copy of continuation state:
    checkpoint (RunContinuationCheckpoint, already validated against
    the Run and the approval by the service that built this) remains
    the one place messages, pending_round_tool_calls,
    pending_tool_call_index, completed_tool_results, and every
    counter/budget live. This class adds exactly what the checkpoint
    cannot already answer - what a human decided (resolution), what
    that decision means operationally right now (next_action), and,
    when something should run, the exact ToolCall to run
    (effective_tool_call) - not a fourth copy of the same schema.

    effective_tool_call is None for REJECT_PENDING_TOOL/CANCEL_RUN (no
    executable action - see ContinuationNextAction), the original
    checkpointed pending ToolCall itself for APPROVE (no copy at all,
    same object), and a *new* ToolCall for MODIFY - same id and name
    as the pending call, but modified_input as the complete
    replacement input, not merged with the original. Constructing a
    new ToolCall (rather than mutating or wrapping the checkpointed
    one - which couldn't be mutated anyway, ToolCall is frozen) is
    what keeps "the original pending ToolCall ... unchanged, including
    for MODIFY" true by construction: checkpoint.pending_round_tool_calls
    is never touched to produce it.

    effective_tool_call is field(repr=False) - matching
    ApprovalRequest.proposed_action/ApprovalResolution.modified_input's
    own reasoning: for MODIFY this is the one field on this class
    capable of carrying raw, unredacted tool input, and repr() is what
    debug output and test-failure messages go through. checkpoint and
    resolution are left un-redacted at *this* layer deliberately, not
    an oversight - both already redact their own sensitive fields
    (RunContinuationCheckpoint.messages/pending_round_tool_calls/
    completed_tool_results, ApprovalResolution.modified_input), so
    double-hiding the whole nested object here would add nothing,
    matching how ToolApprovalGateResult leaves its nested
    ApprovalRequest field un-redacted for the same reason.

    This is a description of validated persisted state, not a reusable
    authorization token or proof of execution - deliberately. A
    consumer must, before dispatching effective_tool_call:

    - Revalidate this same state and acquire a durable execution claim
      (not built in this stage) before doing anything observable - two
      processes racing to resume the same paused Run must not both
      execute the pending call.
    - Recheck current tool authorization through the normal execution
      validation path, including for a MODIFY's effective_tool_call -
      a resolution recorded earlier does not retroactively authorize
      whatever the tool policy says *now*.
    - Apply this resolution only to this exact pending call - never to
      any other call in checkpoint.pending_round_tool_calls.
    - Evaluate later calls (after pending_tool_call_index) normally,
      through whatever ToolApprovalGate/ToolExecutor path any other
      call already goes through - this result says nothing about them.
    - Never automatically replay completed_tool_results - those
      already ran; this result exists to avoid re-running them, not to
      re-describe them as pending.
    """

    task_id: str
    run_id: str
    checkpoint: RunContinuationCheckpoint
    resolution: ApprovalResolution
    next_action: ContinuationNextAction
    effective_tool_call: ToolCall | None = field(
        default=None, repr=False
    )

    def __post_init__(self) -> None:
        for field_name in ("task_id", "run_id"):
            value = getattr(self, field_name)
            if not value or not value.strip():
                raise ValueError(
                    "ApprovalContinuationPreparation field "
                    f"'{field_name}' must be a non-empty string"
                )

        if (
            self.task_id != self.checkpoint.task_id
            or self.run_id != self.checkpoint.run_id
        ):
            raise ValueError(
                "ApprovalContinuationPreparation task_id/run_id "
                f"({self.task_id!r}, {self.run_id!r}) does not match "
                "its checkpoint's "
                f"({self.checkpoint.task_id!r}, "
                f"{self.checkpoint.run_id!r})"
            )

        if self.resolution.approval_id != self.checkpoint.approval_id:
            raise ValueError(
                "ApprovalContinuationPreparation resolution "
                f"approval_id {self.resolution.approval_id!r} does "
                "not match checkpoint approval_id "
                f"{self.checkpoint.approval_id!r}"
            )

        expected_next_action = next_action_for(self.resolution.decision)

        if self.next_action is not expected_next_action:
            raise ValueError(
                "ApprovalContinuationPreparation next_action "
                f"{self.next_action!r} does not match the action "
                f"implied by decision {self.resolution.decision!r} "
                f"({expected_next_action!r})"
            )

        pending_call = self.pending_tool_call

        if (
            self.next_action
            is ContinuationNextAction.EXECUTE_PENDING_TOOL
        ):
            if self.effective_tool_call is None:
                raise ValueError(
                    "ApprovalContinuationPreparation requires "
                    "effective_tool_call when next_action is "
                    "EXECUTE_PENDING_TOOL"
                )

            if (
                self.effective_tool_call.id != pending_call.id
                or self.effective_tool_call.name != pending_call.name
            ):
                raise ValueError(
                    "ApprovalContinuationPreparation "
                    "effective_tool_call must share the pending "
                    "ToolCall's id and name"
                )

            if (
                self.resolution.decision is ApprovalDecision.APPROVE
                and self.effective_tool_call.input != pending_call.input
            ):
                raise ValueError(
                    "ApprovalContinuationPreparation effective_tool_call "
                    "must use the original input for an APPROVE decision"
                )

            if (
                self.resolution.decision is ApprovalDecision.MODIFY
                and self.effective_tool_call.input
                != self.resolution.modified_input
            ):
                raise ValueError(
                    "ApprovalContinuationPreparation effective_tool_call "
                    "must use resolution.modified_input as its complete "
                    "input for a MODIFY decision"
                )
        elif self.effective_tool_call is not None:
            raise ValueError(
                "ApprovalContinuationPreparation must not carry "
                f"effective_tool_call when next_action is "
                f"{self.next_action!r}"
            )

    @property
    def approval_id(self) -> str:
        return self.checkpoint.approval_id

    @property
    def decision(self) -> ApprovalDecision:
        return self.resolution.decision

    @property
    def pending_tool_call(self) -> ToolCall:
        return self.checkpoint.pending_round_tool_calls[
            self.checkpoint.pending_tool_call_index
        ]
