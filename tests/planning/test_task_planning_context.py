from __future__ import annotations

import dataclasses

import pytest

from src.agents.task_agent_info import TaskAgentInfo
from src.planning.task_planning_context import TaskPlanningContext


def test_create_task_planning_context() -> None:
    agent = TaskAgentInfo(agent_id="coder", role="backend developer")

    context = TaskPlanningContext(
        task_id="task-1", available_agents=[agent]
    )

    assert context.task_id == "task-1"
    assert context.available_agents == [agent]


def test_default_constraints() -> None:
    context = TaskPlanningContext(
        task_id="task", available_agents=[]
    )

    assert context.constraints == []


def test_default_project_context_is_none() -> None:
    context = TaskPlanningContext(
        task_id="task", available_agents=[]
    )

    assert context.project_context is None


def test_context_is_frozen() -> None:
    context = TaskPlanningContext(
        task_id="task", available_agents=[]
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        context.task_id = "other"
