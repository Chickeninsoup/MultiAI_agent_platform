from __future__ import annotations

from dataclasses import dataclass, field


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


@dataclass(frozen=True)
class TaskPlan:
    """A Manager's breakdown of a request into ordered TaskSteps."""

    task_id: str
    steps: list[TaskStep]
