from __future__ import annotations

from dataclasses import dataclass

from src.planning.task_planning_context import TaskPlanningContext
from src.retry_manager import RetryableExecutor
from src.task_plan import TaskPlan, TaskStep


@dataclass(frozen=True)
class RecoveryExecutionContext:
    """Everything RecoveryExecutor needs to actually act on a
    RecoveryPlan, bundled so execute() doesn't grow an ever-longer
    parameter list as more RecoveryActions get wired (5E-5C-7C) - RETRY
    needs a TaskStep/executor/task_id, REPAIR_PLAN needs the original
    TaskPlan and a TaskPlanningContext too.

    Per-call state, not something RecoveryExecutor owns or caches -
    the same TaskPlan/executor/TaskPlanningContext a caller already
    has in scope from producing the PlanExecutionResult this
    RecoveryPlan came from.

    steps_by_id is a derived property, not a second constructor field -
    a caller passing plan and a separately-built steps_by_id could let
    the two drift out of sync; deriving it from plan.steps keeps there
    being exactly one source of truth.
    """

    task_id: str
    plan: TaskPlan
    executor: RetryableExecutor
    planning_context: TaskPlanningContext

    @property
    def steps_by_id(self) -> dict[str, TaskStep]:
        return {step.step_id: step for step in self.plan.steps}
