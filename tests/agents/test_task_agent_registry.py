from __future__ import annotations

from src.agents.task_agent import TaskAgent
from src.agents.task_agent_registry import TaskAgentRegistry


def test_assign_agent() -> None:
    registry = TaskAgentRegistry()
    agent = TaskAgent(
        agent_id="agent-1", task_id="task-1", template_id="coder"
    )

    registry.assign_agent(agent)

    assert registry.list_agents("task-1") == [agent]


def test_one_task_can_have_multiple_agents() -> None:
    registry = TaskAgentRegistry()
    coder = TaskAgent("coder", "task-1", "backend")
    reviewer = TaskAgent("reviewer", "task-1", "reviewer")

    registry.assign_agent(coder)
    registry.assign_agent(reviewer)

    agents = registry.list_agents("task-1")

    assert agents == [coder, reviewer]


def test_task_agents_are_isolated() -> None:
    registry = TaskAgentRegistry()
    task_a_agent = TaskAgent("agent-a", "task-a", "coder")
    task_b_agent = TaskAgent("agent-b", "task-b", "coder")

    registry.assign_agent(task_a_agent)
    registry.assign_agent(task_b_agent)

    assert registry.list_agents("task-a") == [task_a_agent]
    assert task_b_agent not in registry.list_agents("task-a")


def test_get_agent() -> None:
    registry = TaskAgentRegistry()
    agent = TaskAgent("agent-1", "task-1", "coder")

    registry.assign_agent(agent)

    assert registry.get_agent("task-1", "agent-1") == agent


def test_cannot_access_agent_from_other_task() -> None:
    registry = TaskAgentRegistry()
    agent = TaskAgent("agent-1", "task-a", "coder")

    registry.assign_agent(agent)

    result = registry.get_agent("task-b", "agent-1")

    assert result is None


def test_remove_task_agents() -> None:
    registry = TaskAgentRegistry()
    agent = TaskAgent("agent-1", "task-a", "coder")

    registry.assign_agent(agent)

    registry.remove_task_agents("task-a")

    assert registry.list_agents("task-a") == []


def test_owner_task_id_returns_assigned_task() -> None:
    registry = TaskAgentRegistry()
    agent = TaskAgent(
        agent_id="agent-coder", task_id="task-a", template_id="coder"
    )

    registry.assign_agent(agent)

    assert registry.owner_task_id("agent-coder") == "task-a"


def test_owner_task_id_returns_none_for_unassigned_agent() -> None:
    registry = TaskAgentRegistry()

    assert registry.owner_task_id("agent-coder") is None


def test_remove_task_agents_clears_ownership() -> None:
    registry = TaskAgentRegistry()
    agent = TaskAgent(
        agent_id="agent-coder", task_id="task-a", template_id="coder"
    )
    registry.assign_agent(agent)

    registry.remove_task_agents("task-a")

    assert registry.owner_task_id("agent-coder") is None
