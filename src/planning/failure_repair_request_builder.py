from __future__ import annotations

from src.execution_failure import ExecutionFailure
from src.planning.plan_repair_request import PlanRepairRequest
from src.planning.repair_request_source import RepairRequestSource
from src.planning.task_planning_context import TaskPlanningContext
from src.planning.validation_error import ValidationError
from src.task_plan import TaskPlan


class FailureRepairRequestBuilder:
    """Converts a runtime ExecutionFailure into a PlanRepairRequest
    (5E-5C-7A) - the entry point RecoveryAction.REPAIR_PLAN will
    eventually route through (5E-5C-7B), not something this class
    triggers itself.

    Deliberate mirror of RepairRequestBuilder (which converts a failed
    PlanValidationResult instead), kept as a separate class rather
    than a second method on it: that builder's job is "the plan itself
    was never valid," this one's is "the plan was valid and something
    failed while running it" - different inputs, different callers,
    and RepairRequestBuilder shouldn't need to know ExecutionFailure
    exists just to serve this case too.

    Never inspects failure.category - by the time RecoveryAction.
    REPAIR_PLAN has been decided, RecoveryPlanner has already made
    that call; re-checking it here would duplicate a decision that
    belongs to exactly one place. This is data conversion only.
    """

    def build(
        self,
        task_id: str,
        plan: TaskPlan,
        failure: ExecutionFailure,
        context: TaskPlanningContext,
    ) -> PlanRepairRequest:
        error = ValidationError(
            code="EXECUTION_FAILURE",
            message=self._build_message(task_id, failure),
            repairable=True,
        )

        return PlanRepairRequest(
            original_plan=plan,
            errors=[error],
            instructions=(
                "Fix the step that failed during execution "
                "and generate a new valid plan."
            ),
            context=context,
            source=RepairRequestSource.EXECUTION_FAILURE,
        )

    def _build_message(
        self, task_id: str, failure: ExecutionFailure
    ) -> str:
        if failure.step_id is not None:
            return (
                f"Execution failed on step {failure.step_id!r} "
                f"(task {task_id!r}): {failure.message}"
            )

        return f"Execution failed (task {task_id!r}): {failure.message}"
