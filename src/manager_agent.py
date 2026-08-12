from __future__ import annotations

from src.task_plan import TaskPlan, TaskStep


class ManagerAgent:
    """Turns a user request into a TaskPlan other Agents can act on.

    First cut of the Manager: no decomposition intelligence yet (that's
    5D-3C's LLM planner). This fixed single-step plan exists to prove
    the wiring - ManagerAgent -> TaskPlan -> TaskPlanConverter ->
    MessageRouter - works end to end before any planning logic exists.
    Manager only plans; converting a TaskPlan into AgentMessages and
    actually routing them is a separate concern (TaskPlanConverter +
    whatever executes the plan), so plan() stops at TaskPlan.
    task_id is caller-supplied rather than generated here, matching
    how every other entry point in this codebase (e.g.
    TaskService.create_task_and_run) takes an explicit task_id instead
    of inventing one internally.
    """

    def plan(self, request: str, task_id: str) -> TaskPlan:
        return TaskPlan(
            task_id=task_id,
            steps=[
                TaskStep(
                    step_id="step-1",
                    agent_id="agent-coder",
                    description=request,
                )
            ],
        )
