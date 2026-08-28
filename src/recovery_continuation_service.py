from __future__ import annotations

from src.planning.plan_execution_result import PlanExecutionResult
from src.planning.task_plan_resume_service import TaskPlanResumeService
from src.recovery_continuation_errors import RecoveryContinuationError
from src.runtime_approval_repository import RuntimeApprovalRepository
from src.task_plan import TaskPlan


class RecoveryContinuationService:
    """The bridge between a human's decision and continued execution
    (5E-5C-8D-6) - turns "this RuntimeApprovalRequest is approved"
    into an actual TaskPlanResumeService.resume() call, and nothing
    else.

    Not RuntimeApprovalService (doesn't create/approve/reject
    anything - only reads the already-decided record) and not
    TaskPlanResumeService (doesn't build resume plans or touch
    TaskScheduler itself - delegates entirely). This class exists so
    neither of those two has to know about the other: RuntimeApprovalService
    stays approval-lifecycle-only, TaskPlanResumeService stays
    checkpoint-resume-only, and this is the one place that gates the
    second on the first.

    Refuses to resume anything unless status is exactly "approved" -
    a pending request (nobody decided yet) or a rejected one (a human
    explicitly said no) must never reach TaskPlanResumeService.resume(),
    raising RecoveryContinuationError instead of silently proceeding
    or silently doing nothing. A missing approval (RuntimeApprovalRepository.
    load raising FileNotFoundError) propagates unhandled, same as every
    other "no record where one was expected" case in this chain.
    """

    def __init__(
        self,
        runtime_approval_repository: RuntimeApprovalRepository,
        task_plan_resume_service: TaskPlanResumeService,
    ) -> None:
        self._runtime_approval_repository = runtime_approval_repository
        self._task_plan_resume_service = task_plan_resume_service

    def resume_after_approval(
        self, task_id: str, plan: TaskPlan
    ) -> PlanExecutionResult:
        approval = self._runtime_approval_repository.load(task_id)

        if approval.status != "approved":
            raise RecoveryContinuationError(
                f"Runtime approval {approval.approval_id!r} has "
                f"status {approval.status!r} - only an approved "
                "request may resume execution"
            )

        return self._task_plan_resume_service.resume(task_id, plan)
