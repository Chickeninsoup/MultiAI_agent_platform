from __future__ import annotations

from src.planning.plan_approval import PlanApproval
from src.step_execution_result import StepExecutionResult
from src.task_scheduler import TaskScheduler


class ApprovedPlanExecutor:
    """Gates a TaskPlan's execution on its PlanApproval status.

    The bridge between the Planning layer and TaskScheduler - the
    only place that knows about both. Scheduler stays ignorant of
    humans, review, and approval entirely; it only ever sees a
    TaskPlan handed to it after this gate has already let it through.
    Rejects a plan that isn't "approved" (pending or rejected alike)
    rather than silently skipping it, since a caller trying to run an
    unapproved plan is a bug worth surfacing, not a no-op.
    """

    def __init__(self, scheduler: TaskScheduler) -> None:
        self._scheduler = scheduler

    def execute(
        self, approval: PlanApproval
    ) -> list[StepExecutionResult]:
        if approval.status != "approved":
            raise ValueError("Plan has not been approved")

        return self._scheduler.run(approval.review.plan)
