from __future__ import annotations

from src.approval_application_status import ApprovalApplicationStatus
from src.approval_inspection_service import ApprovalInspection
from src.approval_request import ApprovalRequest
from src.run_continuation_attempt_status import (
    RunContinuationAttemptStatus,
)


def format_approval_list(requests: list[ApprovalRequest]) -> str:
    if not requests:
        return "No pending tool approvals."

    lines: list[str] = ["Pending Tool Approvals"]

    for request in requests:
        lines.append("")
        lines.append(request.approval_id)
        lines.append(f"Run:    {request.run_id}")
        lines.append(f"Tool:   {request.proposed_action.name}")
        lines.append(f"Risk:   {request.risk_level.value}")
        lines.append(f"Reason: {request.reason}")
        lines.append(f"Preview: {request.input_preview}")
        lines.append(f"Created: {request.created_at}")
        lines.append("Status: pending")

    return "\n".join(lines)


def format_approval_detail(inspection: ApprovalInspection) -> str:
    """Safe fields only, by construction (5E-5D-6D) - every value
    printed here comes from a field this codebase already treats as
    display-safe (ApprovalRequest.input_preview, never
    .proposed_action.input; never ApprovalResolution.modified_input).
    No branch below ever formats a full request/resolution/record
    object - each line names one specific attribute."""

    request = inspection.request
    lines: list[str] = []

    lines.append(f"Approval ID: {request.approval_id}")
    lines.append(f"Run ID:      {request.run_id}")
    lines.append(
        "Task ID:     "
        + (inspection.task_id or "(orphaned - no owning task found)")
    )
    lines.append(f"Tool:        {request.proposed_action.name}")
    lines.append(f"Risk level:  {request.risk_level.value}")
    lines.append(f"Reason:      {request.reason}")
    lines.append(f"Preview:     {request.input_preview}")
    lines.append(f"Created at:  {request.created_at}")
    lines.append("")

    if inspection.resolution is None:
        lines.append("Decision: pending")
        lines.append("")
        lines.append(
            "No decision has been recorded yet. Use "
            "approve-tool-call / reject-tool-call / modify-tool-call "
            "/ cancel-tool-call."
        )

        return "\n".join(lines)

    resolution = inspection.resolution
    lines.append("Decision: recorded")
    lines.append(f"  Value:       {resolution.decision.value}")
    lines.append(f"  Resolved at: {resolution.resolved_at}")

    if resolution.explanation is not None:
        lines.append(f"  Explanation: {resolution.explanation}")

    lines.append(
        "  Modified input: "
        + (
            "(provided, not shown)"
            if resolution.modified_input is not None
            else "(not applicable)"
        )
    )
    lines.append("")

    application_record = inspection.application_record

    if application_record is None:
        lines.append("Application: not yet applied")
        lines.append(
            "  The decision is recorded, but nothing has consumed it "
            "yet. Use: python -m src.main resume-after-approval "
            f"{request.run_id} {request.approval_id}"
        )
    elif application_record.status is ApprovalApplicationStatus.CLAIMED:
        lines.append("Application: in progress or interrupted")
        lines.append(
            "  A claim exists but no outcome has been recorded. This "
            "may mean another process is actively applying this "
            "decision right now, or that an earlier attempt was "
            "interrupted. It will not be retried automatically."
        )
    else:
        outcome = application_record.outcome
        assert outcome is not None
        lines.append("Application: completed")
        lines.append(f"  Next action: {outcome.next_action.value}")

        if outcome.tool_result is not None:
            lines.append(
                f"  Tool result: "
                f"{'success' if outcome.tool_result.success else 'failure'}"
            )

            if outcome.tool_result.error_code is not None:
                lines.append(
                    f"  Error code:  {outcome.tool_result.error_code}"
                )

    lines.append("")
    attempt_record = inspection.attempt_record

    if attempt_record is None:
        lines.append("Run continuation: not yet attempted")
    elif (
        attempt_record.status
        is RunContinuationAttemptStatus.CLAIMED
    ):
        lines.append("Run continuation: in progress or interrupted")
        lines.append(
            "  A continuation attempt is claimed for this Run but has "
            "not completed. It will not be retried automatically."
        )
    else:
        assert attempt_record.transition is not None
        lines.append("Run continuation: completed")
        lines.append(f"  Transition: {attempt_record.transition.value}")

        if attempt_record.new_approval_id is not None:
            lines.append(
                "  New approval: "
                f"{attempt_record.new_approval_id} "
                "(a later tool call in this Run now requires its own "
                "approval)"
            )

    lines.append("")
    lines.append(
        "Note: a resolved decision alone does not mean the tool "
        "executed or the Run ended - see Application/Run continuation "
        "above for what has actually happened."
    )

    return "\n".join(lines)
