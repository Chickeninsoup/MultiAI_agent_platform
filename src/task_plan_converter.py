from __future__ import annotations

from src.agent_message import AgentMessage
from src.task_plan import TaskPlan, TaskStep


class TaskPlanConverter:
    """Turns a TaskPlan's ordered TaskSteps into routable AgentMessages.

    Kept separate from ManagerAgent so this conversion is reusable by
    anything else that produces a TaskPlan later (an API endpoint, a
    scheduler retrying one step) without depending on Manager's
    planning logic.
    """

    def __init__(self, sender_id: str = "agent-manager") -> None:
        self._sender_id = sender_id

    def to_messages(self, plan: TaskPlan) -> list[AgentMessage]:
        return [
            self.step_to_message(step, plan.task_id)
            for step in plan.steps
        ]

    def step_to_message(
        self, step: TaskStep, task_id: str
    ) -> AgentMessage:
        return AgentMessage(
            sender_id=self._sender_id,
            receiver_id=step.agent_id,
            task_id=task_id,
            content=step.description,
            context={},
        )
