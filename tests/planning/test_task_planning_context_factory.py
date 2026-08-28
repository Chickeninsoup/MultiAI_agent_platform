from __future__ import annotations

import pytest

from src.agents.agent_errors import AgentTemplateNotFoundError
from src.agents.agent_template import AgentTemplate
from src.agents.agent_template_repository import (
    AgentTemplateRepository,
)
from src.agents.task_agent import TaskAgent
from src.agents.task_agent_info import TaskAgentInfo
from src.agents.task_agent_registry import TaskAgentRegistry
from src.planning.task_planning_context_factory import (
    TaskPlanningContextFactory,
)


def _factory() -> tuple[
    TaskPlanningContextFactory, TaskAgentRegistry, AgentTemplateRepository
]:
    registry = TaskAgentRegistry()
    templates = AgentTemplateRepository()
    return TaskPlanningContextFactory(registry, templates), registry, templates


def test_factory_creates_context_with_task_agents() -> None:
    factory, registry, templates = _factory()
    templates.save(
        AgentTemplate(
            template_id="coder",
            name="Backend Developer",
            description="Writes backend code",
            capabilities=["python"],
        )
    )
    registry.assign_agent(TaskAgent("a", "task-a", "coder"))

    context = factory.create("task-a")

    assert context.task_id == "task-a"
    assert context.available_agents == [
        TaskAgentInfo(
            agent_id="a",
            role="Backend Developer",
            description="Writes backend code",
            capabilities=["python"],
        )
    ]


def test_factory_only_uses_task_agents() -> None:
    factory, registry, templates = _factory()
    templates.save(AgentTemplate(template_id="coder", name="Coder"))
    templates.save(AgentTemplate(template_id="reviewer", name="Reviewer"))
    registry.assign_agent(TaskAgent("a", "task-a", "coder"))
    registry.assign_agent(TaskAgent("b", "task-b", "reviewer"))

    context = factory.create("task-a")

    assert context.available_agents == [
        TaskAgentInfo(agent_id="a", role="Coder")
    ]


def test_factory_empty_when_no_agents_assigned() -> None:
    factory, _registry, _templates = _factory()

    context = factory.create("task-nonexistent")

    assert context.available_agents == []


def test_factory_preserves_multiple_agents_in_order() -> None:
    factory, registry, templates = _factory()
    templates.save(AgentTemplate(template_id="coder", name="Coder"))
    templates.save(AgentTemplate(template_id="reviewer", name="Reviewer"))
    registry.assign_agent(TaskAgent("a", "task-a", "coder"))
    registry.assign_agent(TaskAgent("c", "task-a", "reviewer"))

    context = factory.create("task-a")

    assert context.available_agents == [
        TaskAgentInfo(agent_id="a", role="Coder"),
        TaskAgentInfo(agent_id="c", role="Reviewer"),
    ]


def test_factory_raises_when_template_is_missing() -> None:
    factory, registry, _templates = _factory()
    registry.assign_agent(TaskAgent("a", "task-a", "unregistered"))

    with pytest.raises(AgentTemplateNotFoundError):
        factory.create("task-a")


def test_template_can_be_reused_across_tasks_but_agent_instances_cannot() -> (
    None
):
    factory, registry, templates = _factory()
    templates.save(AgentTemplate(template_id="coder", name="Coder"))
    registry.assign_agent(TaskAgent("a", "task-a", "coder"))
    registry.assign_agent(TaskAgent("b", "task-b", "coder"))

    context_a = factory.create("task-a")
    context_b = factory.create("task-b")

    assert context_a.available_agents == [
        TaskAgentInfo(agent_id="a", role="Coder")
    ]
    assert context_b.available_agents == [
        TaskAgentInfo(agent_id="b", role="Coder")
    ]
