from __future__ import annotations

import dataclasses

import pytest

from src.agents.task_agent_info import TaskAgentInfo


def test_create_agent_info() -> None:
    info = TaskAgentInfo(agent_id="agent-1", role="backend developer")

    assert info.agent_id == "agent-1"
    assert info.role == "backend developer"


def test_capabilities_default() -> None:
    info = TaskAgentInfo(agent_id="agent", role="coder")

    assert info.description == ""
    assert info.capabilities == []


def test_agent_info_frozen() -> None:
    info = TaskAgentInfo(agent_id="agent", role="coder")

    with pytest.raises(dataclasses.FrozenInstanceError):
        info.role = "reviewer"
