from __future__ import annotations

import dataclasses

import pytest

from src.agents.task_agent import TaskAgent


def test_create_task_agent() -> None:
    agent = TaskAgent(
        agent_id="agent-1", task_id="task-1", template_id="backend"
    )

    assert agent.agent_id == "agent-1"
    assert agent.task_id == "task-1"
    assert agent.template_id == "backend"


def test_default_status() -> None:
    agent = TaskAgent(
        agent_id="agent", task_id="task", template_id="template"
    )

    assert agent.status == "active"


def test_task_agent_frozen() -> None:
    agent = TaskAgent(
        agent_id="agent", task_id="task", template_id="template"
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        agent.task_id = "other"
