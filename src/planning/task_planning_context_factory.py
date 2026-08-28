from __future__ import annotations

from src.agents.agent_errors import AgentTemplateNotFoundError
from src.agents.agent_template_repository import (
    AgentTemplateRepository,
)
from src.agents.task_agent import TaskAgent
from src.agents.task_agent_info import TaskAgentInfo
from src.agents.task_agent_registry import TaskAgentRegistry
from src.planning.task_planning_context import TaskPlanningContext


class TaskPlanningContextFactory:
    """Turns "what agents does this task have" into a Planner input.

    Keeps TaskAgentRegistry's job ("what agent instances exist for
    this task") separate from AgentTemplateRepository's job ("what
    does this template_id mean") - this is the one place both get
    joined into the Planner-facing TaskAgentInfo shape. Raises
    AgentTemplateNotFoundError if a TaskAgent's template_id doesn't
    resolve, rather than silently degrading to template_id-as-role: a
    TaskAgent referencing a missing template means runtime state is
    corrupt (assigned before the template existed, or the template
    was deleted from under it), and Claude shouldn't be handed a
    plan built on data that's already known to be broken.
    """

    def __init__(
        self,
        registry: TaskAgentRegistry,
        template_repository: AgentTemplateRepository,
    ) -> None:
        self._registry = registry
        self._template_repository = template_repository

    def create(self, task_id: str) -> TaskPlanningContext:
        agents = self._registry.list_agents(task_id)

        infos = [self._to_info(agent) for agent in agents]

        return TaskPlanningContext(
            task_id=task_id, available_agents=infos
        )

    def _to_info(self, agent: TaskAgent) -> TaskAgentInfo:
        template = self._template_repository.get(agent.template_id)

        if template is None:
            raise AgentTemplateNotFoundError(
                f"TaskAgent {agent.agent_id!r} references unknown "
                f"template {agent.template_id!r}"
            )

        return TaskAgentInfo(
            agent_id=agent.agent_id,
            role=template.name,
            description=template.description,
            capabilities=list(template.capabilities),
        )
