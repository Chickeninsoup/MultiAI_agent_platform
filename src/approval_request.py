from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from src.approval_status import ApprovalStatus
from src.clock import utc_now
from src.domain.tools.tool_call import ToolCall


class RiskLevel(Enum):
    """How dangerous a proposed action is judged to be, for whatever
    displays an ApprovalRequest to a human (5E-5D-1).

    No risk-grading type already existed in this codebase to reuse
    (src/review/review_report.py's `risks` is a free-text list, not a
    graded level) - this is the minimal closed vocabulary needed to
    let a human triage several pending requests at a glance, matching
    this codebase's habit of small fixed-membership Enums
    (FailureCategory, RecoveryAction, StepStatus) over free text for
    anything a caller might branch on.

    LOW - unlikely to cause meaningful harm if wrong (e.g. a read).

    MEDIUM - reversible but consequential (e.g. a scoped file write).

    HIGH - hard or impossible to reverse, or broad in effect (e.g.
    deleting data, an irreversible external side effect).
    """

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


@dataclass(frozen=True)
class ApprovalRequest:
    """A pending ask for a human to decide whether one proposed
    action may run (5E-5D-1) - the domain model behind
    RecoveryAction.REQUEST_APPROVAL and, more generally, any flow that
    wants a human in the loop before a specific action executes.

    Deliberately not the same model as RuntimeApprovalRequest
    (src/runtime_approval_request.py): that one answers "may recovery
    continue after this Task's plan execution hit a BLOCKED failure" -
    coarse, plan-scoped, carries a whole ExecutionFailure. This one
    answers "may this one proposed action run" - scoped to a single
    action (proposed_action), carries no ExecutionFailure at all, and
    can be resolved with MODIFY/CANCEL as well as approve/reject,
    which RuntimeApprovalRequest's status has no room for. Nor is it
    ApprovalRecord/PlanApproval (Plan Approval - "may this TaskPlan
    start executing at all"). Four different "approval" concepts now
    exist in this codebase for four different questions; whether/how
    any of them consolidate is left to a later stage - 5E-5D-1 is
    model only, not wired into RecoveryExecutor or anything else.

    run_id ties this back to the Run (RunDefinition.id) whose
    execution produced the proposed action - a Run is what actually
    issues ToolCalls (src/llm_executor.py), so it's the natural
    "originating" identifier here, not task_id/plan_id (those identify
    *why* a Run exists, not which execution proposed this action).

    proposed_action is a real ToolCall (src/domain/tools/tool_call.py),
    reused as-is rather than re-modeled - it already carries exactly
    what's needed to actually execute the action if approved (id,
    name, input), and reusing it means an approval flow can eventually
    hand this straight to whatever runs a ToolCall today without a
    translation step.

    input_preview is deliberately a *separate* field from
    proposed_action.input, not a formatting of it: proposed_action
    carries the real input (needed to execute after approval),
    input_preview is a caller-constructed, human-safe summary of it.
    This model has no way to know which fields of an arbitrary tool's
    input are sensitive for a given tool, so it cannot redact
    proposed_action.input itself - whatever builds an ApprovalRequest
    is responsible for making input_preview safe to display (no
    secrets, no unrestricted raw input dumped verbatim). The
    invariant this model *can* enforce is only that a preview exists
    and isn't empty; it cannot verify what's inside it is actually
    safe.

    risk_level uses RiskLevel (this file) since no existing risk type
    was found elsewhere in the codebase to reuse (see RiskLevel's own
    docstring).

    status defaults to PENDING (every new ApprovalRequest starts
    undecided) but is not pinned there - a caller reconstructing a
    resolved request from storage (from_dict) needs to be able to set
    it to RESOLVED directly. Nothing in this file transitions a
    request from PENDING to RESOLVED; that lifecycle (matching
    RuntimeApprovalService's approve()/reject() shape) is left to a
    later stage, same as this task's scope excludes it.

    proposed_action is excluded from the auto-generated __repr__
    (field(repr=False), 5E-5D-4A-1) - it carries the real ToolCall,
    including its raw, unredacted input (see proposed_action's own
    paragraph above for why that's intentional for persistence/
    execution). repr() is what ordinary debug output, logging, and
    test-failure messages go through; input_preview exists precisely
    so a human never needs the raw input to understand what's
    pending, so nothing about proposed_action needs to appear in
    ordinary repr output at all. This does not affect equality
    (field(repr=False) leaves compare=True untouched, so == still
    compares proposed_action) or to_dict()/from_dict() (both
    untouched, still serialize the real proposed_action in full) -
    only str(request)/repr(request) change.
    """

    approval_id: str
    run_id: str
    proposed_action: ToolCall = field(repr=False)
    reason: str
    risk_level: RiskLevel
    input_preview: str
    created_at: str = field(default_factory=utc_now)
    status: ApprovalStatus = ApprovalStatus.PENDING

    def __post_init__(self) -> None:
        for field_name in (
            "approval_id",
            "run_id",
            "reason",
            "input_preview",
        ):
            value = getattr(self, field_name)
            if not value or not value.strip():
                raise ValueError(
                    f"ApprovalRequest field '{field_name}' must be a "
                    "non-empty string"
                )

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "run_id": self.run_id,
            "proposed_action": {
                "id": self.proposed_action.id,
                "name": self.proposed_action.name,
                "input": self.proposed_action.input,
            },
            "reason": self.reason,
            "risk_level": self.risk_level.value,
            "input_preview": self.input_preview,
            "created_at": self.created_at,
            "status": self.status.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ApprovalRequest":
        action_data = data["proposed_action"]

        return cls(
            approval_id=data["approval_id"],
            run_id=data["run_id"],
            proposed_action=ToolCall(
                id=action_data["id"],
                name=action_data["name"],
                input=action_data["input"],
            ),
            reason=data["reason"],
            risk_level=RiskLevel(data["risk_level"]),
            input_preview=data["input_preview"],
            created_at=data["created_at"],
            status=ApprovalStatus(data["status"]),
        )
