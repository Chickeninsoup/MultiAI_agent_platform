from __future__ import annotations

from src.message_router import MessageRouter
from src.task_plan import TaskPlan, TaskStep
from src.task_plan_converter import TaskPlanConverter


class TaskPlanExecutor:
    """Runs TaskSteps against the Agents that should do them.

    Deliberately not ManagerAgent's job: planning and executing are
    separate concerns, so Manager stays a pure planner while this owns
    dispatch. execute() runs a whole plan sequentially, in TaskPlan
    order. execute_step() dispatches exactly one step and is what
    TaskScheduler (5D-4C/5D-4D) calls per step of a dependency-round
    wave, in parallel or not - this class only knows how to send one
    step, never when or how many at once. execute_steps() is the
    sequential fallback built from execute_step().
    """

    def __init__(
        self,
        converter: TaskPlanConverter,
        router: MessageRouter,
    ) -> None:
        self._converter = converter
        self._router = router

    def execute(self, plan: TaskPlan) -> list[str]:
        return self.execute_steps(plan.steps, plan.task_id)

    def execute_steps(
        self, steps: list[TaskStep], task_id: str
    ) -> list[str]:
        return [
            self.execute_step(step, task_id) for step in steps
        ]

    def execute_step(self, step: TaskStep, task_id: str) -> str:
        message = self._converter.step_to_message(step, task_id)

        return self._router.send(message)
