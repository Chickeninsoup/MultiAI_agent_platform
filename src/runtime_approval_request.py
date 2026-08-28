from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from src.clock import utc_now
from src.execution_failure import ExecutionFailure


@dataclass(frozen=True)
class RuntimeApprovalRequest:
    """A human's pending decision on whether a blocked execution
    failure may be recovered from (5E-5C-8D-2) - deliberately a
    distinct model from ApprovalRecord/PlanApproval, not an extension
    of either.

    Plan Approval answers "may this plan start executing at all,"
    resolved once, before any step ever runs. This answers "execution
    already started and hit a BLOCKED failure mid-plan - may recovery
    continue," which can happen zero or many times over one Task's
    lifetime, at a completely different point in the execution
    timeline. Reusing ApprovalRecord (one file per task_id) would
    collide with and overwrite the Plan Approval record for the same
    task the moment both existed (5E-5C-8D-1 audit finding) - a
    different model, on a different persistence path, is not
    optional here.

    approval_id exists separately from task_id because one Task can
    hit BLOCKED more than once across its lifetime (a second recovery
    after the first one resolves) - task_id alone can't distinguish
    which recovery attempt a decision belongs to. plan_id records
    which Plan attempt this recovery belongs to, for the same reason
    ExecutionCheckpoint carries one. failure is carried in full
    (5E-5A's ExecutionFailure, not a summary string) so whatever
    displays this request to a human can explain what actually went
    wrong, not just that something did.

    status is a plain str default "pending", matching ApprovalRecord/
    PlanApproval/RunDefinition's established convention in this
    codebase rather than an Enum - this model does not enforce
    transitions itself (5E-5C-8D-2 scope is model only); whatever
    eventually owns the approve/reject lifecycle (RuntimeApprovalService,
    a later stage) is responsible for producing a new instance via
    dataclasses.replace with a different status, not mutating this one.
    """

    approval_id: str
    task_id: str
    plan_id: str
    failure: ExecutionFailure
    created_at: str = field(default_factory=utc_now)
    status: str = "pending"

    def to_dict(self) -> dict[str, Any]:
        return {
            "approval_id": self.approval_id,
            "task_id": self.task_id,
            "plan_id": self.plan_id,
            "failure": self.failure.to_dict(),
            "created_at": self.created_at,
            "status": self.status,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "RuntimeApprovalRequest":
        return cls(
            approval_id=data["approval_id"],
            task_id=data["task_id"],
            plan_id=data["plan_id"],
            failure=ExecutionFailure.from_dict(data["failure"]),
            created_at=data["created_at"],
            status=data["status"],
        )
