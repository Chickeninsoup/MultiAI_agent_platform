from __future__ import annotations

from src.agents.agent_template import AgentTemplate
from src.agents.agent_template_repository import (
    AgentTemplateRepository,
)
from src.agents.task_agent_assignment_service import (
    TaskAgentAssignmentService,
)
from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.planning.task_planning_context_factory import (
    TaskPlanningContextFactory,
)


class FakeAgentDefinition:
    def __init__(self, agent_id: str, template_id: str) -> None:
        self.id = agent_id
        self.template_id = template_id


class FakeAgentRegistry:
    def __init__(
        self, agent_ids: list[str], template_id: str = "coder"
    ) -> None:
        self._agent_ids = set(agent_ids)
        self._template_id = template_id

    def get_agent(self, agent_id: str) -> FakeAgentDefinition:
        if agent_id not in self._agent_ids:
            raise FileNotFoundError(agent_id)

        return FakeAgentDefinition(agent_id, self._template_id)


class FakeTaskRepository:
    def __init__(self, task_ids: list[str]) -> None:
        self._task_ids = set(task_ids)

    def load(self, task_id: str) -> object:
        if task_id not in self._task_ids:
            raise FileNotFoundError(task_id)

        return object()


def test_assignment_flows_into_the_task_planning_context() -> None:
    task_agent_registry = TaskAgentRegistry()
    templates = AgentTemplateRepository()
    templates.save(
        AgentTemplate(template_id="coder", name="Backend Developer")
    )
    assignment_service = TaskAgentAssignmentService(
        FakeAgentRegistry(["agent-coder"]),
        task_agent_registry,
        FakeTaskRepository(["task-a"]),
        TaskAgentTeamLifecycle(task_agent_registry),
    )
    context_factory = TaskPlanningContextFactory(
        task_agent_registry, templates
    )

    assignment_service.assign("task-a", "agent-coder", "coder")
    context = context_factory.create("task-a")

    assert [
        agent.agent_id for agent in context.available_agents
    ] == ["agent-coder"]


def test_assignment_does_not_leak_into_other_tasks_context() -> None:
    task_agent_registry = TaskAgentRegistry()
    templates = AgentTemplateRepository()
    templates.save(
        AgentTemplate(template_id="coder", name="Backend Developer")
    )
    assignment_service = TaskAgentAssignmentService(
        FakeAgentRegistry(["agent-coder"]),
        task_agent_registry,
        FakeTaskRepository(["task-a", "task-b"]),
        TaskAgentTeamLifecycle(task_agent_registry),
    )
    context_factory = TaskPlanningContextFactory(
        task_agent_registry, templates
    )

    assignment_service.assign("task-a", "agent-coder", "coder")
    context_b = context_factory.create("task-b")

    assert context_b.available_agents == []
