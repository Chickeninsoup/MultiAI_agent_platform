from __future__ import annotations

from dataclasses import dataclass, field

from src.agents.task_agent_info import TaskAgentInfo
from src.context.context_snapshot import ContextSnapshot


@dataclass(frozen=True)
class TaskPlanningContext:
    """The Task-scoped replacement for PlanningContext's available_agents.

    Carries TaskAgentInfo (not TaskAgent, not raw agent_ids) - a
    Planner should only ever see the Planner-facing view built by
    TaskPlanningContextFactory from TaskAgentRegistry, never construct
    or assume an agent that isn't actually assigned to this task_id.
    project_context is optional because not every planning call needs
    project file context (e.g. tests), same reasoning as
    PlanningContext.constraints defaulting to empty.
    """

    task_id: str
    available_agents: list[TaskAgentInfo]
    constraints: list[str] = field(default_factory=list)
    project_context: ContextSnapshot | None = None
