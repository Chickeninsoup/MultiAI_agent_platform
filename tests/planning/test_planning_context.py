from __future__ import annotations

import dataclasses

import pytest

from src.planning.planning_context import PlanningContext


def test_default_context() -> None:
    context = PlanningContext()

    assert context.available_agents == []
    assert context.constraints == []


def test_context_values() -> None:
    context = PlanningContext(
        available_agents=["agent-coder"],
        constraints=["no destructive changes"],
    )

    assert "agent-coder" in context.available_agents
    assert "no destructive changes" in context.constraints


def test_context_is_frozen() -> None:
    context = PlanningContext()

    with pytest.raises(dataclasses.FrozenInstanceError):
        context.constraints = []
