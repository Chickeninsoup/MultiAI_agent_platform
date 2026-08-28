from __future__ import annotations

import pytest

from src.agents.task_agent import TaskAgent
from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.agents.task_agent_team_lifecycle_errors import (
    TaskAgentTeamStateError,
)
from src.agents.task_agent_team_state import TaskAgentTeamState


def test_unseen_task_defaults_to_open() -> None:
    lifecycle = TaskAgentTeamLifecycle(TaskAgentRegistry())

    assert lifecycle.state("task-a") is TaskAgentTeamState.OPEN


def test_lock_moves_open_to_locked() -> None:
    lifecycle = TaskAgentTeamLifecycle(TaskAgentRegistry())

    lifecycle.lock("task-a")

    assert lifecycle.state("task-a") is TaskAgentTeamState.LOCKED


def test_lock_is_idempotent_when_already_locked() -> None:
    lifecycle = TaskAgentTeamLifecycle(TaskAgentRegistry())
    lifecycle.lock("task-a")

    lifecycle.lock("task-a")

    assert lifecycle.state("task-a") is TaskAgentTeamState.LOCKED


def test_release_moves_locked_to_released() -> None:
    lifecycle = TaskAgentTeamLifecycle(TaskAgentRegistry())
    lifecycle.lock("task-a")

    lifecycle.release("task-a")

    assert lifecycle.state("task-a") is TaskAgentTeamState.RELEASED


def test_lock_after_release_is_rejected() -> None:
    lifecycle = TaskAgentTeamLifecycle(TaskAgentRegistry())
    lifecycle.lock("task-a")
    lifecycle.release("task-a")

    with pytest.raises(TaskAgentTeamStateError):
        lifecycle.lock("task-a")

    assert lifecycle.state("task-a") is TaskAgentTeamState.RELEASED


def test_release_clears_the_registry_membership() -> None:
    registry = TaskAgentRegistry()
    registry.assign_agent(
        TaskAgent(
            agent_id="agent-coder", task_id="task-a", template_id="coder"
        )
    )
    lifecycle = TaskAgentTeamLifecycle(registry)

    lifecycle.release("task-a")

    assert registry.list_agents("task-a") == []


def test_release_clears_the_ownership_index() -> None:
    registry = TaskAgentRegistry()
    registry.assign_agent(
        TaskAgent(
            agent_id="agent-coder", task_id="task-a", template_id="coder"
        )
    )
    lifecycle = TaskAgentTeamLifecycle(registry)

    lifecycle.release("task-a")

    assert registry.owner_task_id("agent-coder") is None


def test_release_does_not_affect_other_tasks() -> None:
    registry = TaskAgentRegistry()
    registry.assign_agent(
        TaskAgent(
            agent_id="agent-a", task_id="task-a", template_id="coder"
        )
    )
    registry.assign_agent(
        TaskAgent(
            agent_id="agent-b", task_id="task-b", template_id="coder"
        )
    )
    lifecycle = TaskAgentTeamLifecycle(registry)

    lifecycle.release("task-a")

    assert [
        agent.agent_id for agent in registry.list_agents("task-b")
    ] == ["agent-b"]
