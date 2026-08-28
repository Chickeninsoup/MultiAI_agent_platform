from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class TaskStep:
    """One unit of work within a TaskPlan: who should do what.

    depends_on lists the step_ids that must complete before this step
    runs. Defaults to empty so existing TaskSteps stay independent.
    This is data only for 5D-4A - a scheduler that actually respects
    depends_on belongs to a later stage.
    """

    step_id: str
    agent_id: str
    description: str
    depends_on: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "step_id": self.step_id,
            "agent_id": self.agent_id,
            "description": self.description,
            "depends_on": list(self.depends_on),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskStep":
        return cls(
            step_id=data["step_id"],
            agent_id=data["agent_id"],
            description=data["description"],
            depends_on=list(data.get("depends_on", [])),
        )


@dataclass(frozen=True)
class TaskPlan:
    """A Manager's breakdown of a request into ordered TaskSteps."""

    task_id: str
    steps: list[TaskStep]

    def to_dict(self) -> dict[str, Any]:
        return {
            "task_id": self.task_id,
            "steps": [step.to_dict() for step in self.steps],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TaskPlan":
        return cls(
            task_id=data["task_id"],
            steps=[
                TaskStep.from_dict(step_data)
                for step_data in data["steps"]
            ],
        )
