from __future__ import annotations

import dataclasses

from src.execution_failure import ExecutionFailure
from src.runtime_approval_errors import RuntimeApprovalStateError
from src.runtime_approval_repository import RuntimeApprovalRepository
from src.runtime_approval_request import RuntimeApprovalRequest


class RuntimeApprovalService:
    """Owns the RuntimeApprovalRequest lifecycle: create pending,
    approve, reject (5E-5C-8D-4) - and nothing past that.

    Does not resume, does not touch Task/Run status, does not touch
    ExecutionCheckpoint, does not execute anything. "A human decided"
    is the entire scope of this class; turning that decision into
    continued execution is RecoveryContinuationService's job (a later
    stage), kept separate the same way RuntimePlanRepairService stays
    ignorant of what happens after a repaired plan comes back.

    approve()/reject() only accept a request whose status is still
    "pending" - approving an already-rejected request (or vice versa)
    would silently overwrite a decision a human already made, which is
    exactly the kind of state corruption this whole approval model
    exists to prevent. Raises RuntimeApprovalStateError, not a bare
    ValueError, so callers can distinguish "wrong lifecycle state" from
    a generic bad-argument error.

    approval_id is derived from the task's existing runtime approval
    (if any) rather than a random id - consistent with this codebase's
    established id-generation style (RunService._next_run_id), not a
    new uuid-based convention. Since RuntimeApprovalRepository only
    ever keeps one active record per task, "next id" means "increment
    the previous one for this task," not "scan a list."
    """

    def __init__(self, repository: RuntimeApprovalRepository) -> None:
        self._repository = repository

    def create(
        self,
        task_id: str,
        plan_id: str,
        failure: ExecutionFailure,
    ) -> RuntimeApprovalRequest:
        request = RuntimeApprovalRequest(
            approval_id=self._next_approval_id(task_id),
            task_id=task_id,
            plan_id=plan_id,
            failure=failure,
        )
        self._repository.save(request)

        return request

    def approve(self, task_id: str) -> RuntimeApprovalRequest:
        return self._transition(task_id, "approved")

    def reject(self, task_id: str) -> RuntimeApprovalRequest:
        return self._transition(task_id, "rejected")

    def _transition(
        self, task_id: str, new_status: str
    ) -> RuntimeApprovalRequest:
        request = self._repository.load(task_id)

        if request.status != "pending":
            raise RuntimeApprovalStateError(
                f"Runtime approval {request.approval_id!r} has status "
                f"{request.status!r} and cannot be transitioned to "
                f"{new_status!r} - only a pending request can be "
                "decided"
            )

        decided = dataclasses.replace(request, status=new_status)
        self._repository.save(decided)

        return decided

    def _next_approval_id(self, task_id: str) -> str:
        prefix = f"{task_id}-approval-"

        try:
            existing = self._repository.load(task_id)
        except FileNotFoundError:
            return f"{prefix}1"

        suffix = existing.approval_id.removeprefix(prefix)

        if suffix.isdigit():
            return f"{prefix}{int(suffix) + 1}"

        return f"{prefix}1"
