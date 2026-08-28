from __future__ import annotations

import dataclasses

import pytest

from src.planning.plan_schema import PlannedStep


def test_planned_step_fields() -> None:
    step = PlannedStep("a", "coder", "implement", [])

    assert step.step_id == "a"
    assert step.agent_id == "coder"
    assert step.description == "implement"
    assert step.depends_on == []


def test_planned_step_depends_on_defaults_to_empty() -> None:
    step = PlannedStep(
        step_id="a", agent_id="coder", description="implement"
    )

    assert step.depends_on == []


def test_planned_step_can_declare_dependencies() -> None:
    step = PlannedStep(
        step_id="b",
        agent_id="coder",
        description="implement",
        depends_on=["a"],
    )

    assert step.depends_on == ["a"]


def test_planned_step_is_frozen() -> None:
    step = PlannedStep("a", "coder", "implement", [])

    with pytest.raises(dataclasses.FrozenInstanceError):
        step.agent_id = "researcher"
