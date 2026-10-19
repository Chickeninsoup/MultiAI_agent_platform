from __future__ import annotations

from enum import Enum

from src.approval_decision import ApprovalDecision


class ContinuationNextAction(Enum):
    """What ApprovalContinuationPreparationService.prepare() says a
    future execution-resume stage must do next (5E-5D-6A) - a
    separate vocabulary from ApprovalDecision on purpose, the same way
    ToolApprovalGateOutcome deliberately sits apart from both
    ToolApprovalRequirement and ApprovalDecision (see that enum's own
    docstring): ApprovalDecision is *what a human chose*; this is
    *what effect that choice has on the paused tool-call loop*. APPROVE
    and MODIFY are different decisions but the same next action
    (execute something), so collapsing the two vocabularies into one
    would either lose "was this modified" or force a caller to
    re-derive it from a side channel.

    EXECUTE_PENDING_TOOL - run the pending ToolCall. For APPROVE, that
    is the original checkpointed call, unchanged. For MODIFY, it is an
    effective call with the same id/name but modified_input as the
    complete replacement input (see
    ApprovalContinuationPreparation.effective_tool_call). Either way,
    only the one pending call is affected; later calls in
    pending_round_tool_calls are untouched and must still go through
    normal authorization/approval evaluation.

    REJECT_PENDING_TOOL - do not execute the pending ToolCall. No
    effective_tool_call is provided. The consumer must synthesize a
    truthful rejection ToolResult for the pending call's id (so the
    conversation the model sees remains protocol-valid), then continue
    processing any later calls in their original order - not here,
    this is description only.

    CANCEL_RUN - stop the Run. No effective_tool_call is provided, and
    no later call (pending or otherwise) should execute.
    """

    EXECUTE_PENDING_TOOL = "execute_pending_tool"
    REJECT_PENDING_TOOL = "reject_pending_tool"
    CANCEL_RUN = "cancel_run"


_NEXT_ACTION_BY_DECISION: dict[ApprovalDecision, ContinuationNextAction] = {
    ApprovalDecision.APPROVE: ContinuationNextAction.EXECUTE_PENDING_TOOL,
    ApprovalDecision.MODIFY: ContinuationNextAction.EXECUTE_PENDING_TOOL,
    ApprovalDecision.REJECT: ContinuationNextAction.REJECT_PENDING_TOOL,
    ApprovalDecision.CANCEL: ContinuationNextAction.CANCEL_RUN,
}


def next_action_for(decision: ApprovalDecision) -> ContinuationNextAction:
    """The single source of truth for ApprovalDecision ->
    ContinuationNextAction, shared by ApprovalContinuationPreparationService
    (which derives next_action from a resolution) and
    ApprovalContinuationPreparation.__post_init__ (which re-checks the
    same mapping holds) - one dict, not two independently maintained
    copies that could drift apart.
    """

    return _NEXT_ACTION_BY_DECISION[decision]
