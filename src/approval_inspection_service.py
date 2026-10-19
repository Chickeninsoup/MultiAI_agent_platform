from __future__ import annotations

from dataclasses import dataclass

from src.approval_application_record import ApprovalApplicationRecord
from src.approval_application_repository import (
    ApprovalApplicationRepository,
)
from src.approval_request import ApprovalRequest
from src.approval_resolution import ApprovalResolution
from src.approval_store import ApprovalStore
from src.repositories import RunRepository, TaskRepository
from src.run_continuation_attempt_record import (
    RunContinuationAttemptRecord,
)
from src.run_continuation_attempt_repository import (
    RunContinuationAttemptRepository,
)


@dataclass(frozen=True)
class ApprovalInspection:
    """A read-only snapshot of everything safe to show a human about
    one ApprovalRequest, across every stage this feature now has
    (5E-5D-6D): raised (request), decided (resolution), applied
    (application_record, from ApprovalApplicationRepository - 5E-5D-
    6B), and the Run-wide continuation chapter it belongs to
    (attempt_record, from RunContinuationAttemptRepository - 5E-5D-
    6C). Any of resolution/application_record/attempt_record/task_id
    may be None - "not reached that stage yet" (resolution/
    application_record/attempt_record) or "orphaned, no owning task
    found" (task_id) are all real, inspectable states this type must
    represent without raising, not failure modes. Deliberately carries
    no checkpoint - RunContinuationCheckpoint.messages/
    pending_round_tool_calls/completed_tool_results are not
    display-safe or even needed for this inspection's purpose.
    """

    request: ApprovalRequest
    resolution: ApprovalResolution | None
    application_record: ApprovalApplicationRecord | None
    attempt_record: RunContinuationAttemptRecord | None
    task_id: str | None


class ApprovalInspectionService:
    """Read-only counterpart to ApprovalDecisionService/
    ApprovalApplicationService/RunService.resume_after_approval(),
    matching RunQueryService's own split from RunService (5E-5D-6D) -
    this never records a decision, applies one, or continues a Run;
    it only reads already-persisted state from ApprovalStore,
    ApprovalApplicationRepository, and RunContinuationAttemptRepository
    and combines it into one inspectable view.
    """

    def __init__(
        self,
        approval_store: ApprovalStore,
        application_repository: ApprovalApplicationRepository,
        attempt_repository: RunContinuationAttemptRepository,
        task_repository: TaskRepository,
        run_repository: RunRepository,
    ) -> None:
        self._approval_store = approval_store
        self._application_repository = application_repository
        self._attempt_repository = attempt_repository
        self._task_repository = task_repository
        self._run_repository = run_repository

    def list_pending(
        self, run_id: str | None = None
    ) -> list[ApprovalRequest]:
        return self._approval_store.list_pending(run_id=run_id)

    def inspect(self, approval_id: str) -> ApprovalInspection:
        request = self._approval_store.get(approval_id)
        resolution = self._approval_store.get_resolution(approval_id)
        application_record = self._application_repository.try_load(
            approval_id
        )

        task_id = self._find_task_id_for_run(request.run_id)
        attempt_record = (
            self._attempt_repository.try_load(
                task_id, request.run_id, approval_id
            )
            if task_id is not None
            else None
        )

        return ApprovalInspection(
            request=request,
            resolution=resolution,
            application_record=application_record,
            attempt_record=attempt_record,
            task_id=task_id,
        )

    def _find_task_id_for_run(self, run_id: str) -> str | None:
        for task in self._task_repository.list_all():
            if run_id in self._run_repository.list_run_ids(task.id):
                return task.id

        return None
