from __future__ import annotations

import dataclasses

import pytest

from src.planning.plan_schema import PlannedStep
from src.planning.planner_output import PlannerOutput


def test_default_output() -> None:
    output = PlannerOutput()

    assert output.steps == []


def test_output_contains_steps() -> None:
    step = PlannedStep(
        step_id="research",
        agent_id="agent-researcher",
        description="research issue",
        depends_on=[],
    )

    output = PlannerOutput(steps=[step])

    assert output.steps == [step]


def test_output_frozen() -> None:
    output = PlannerOutput()

    with pytest.raises(dataclasses.FrozenInstanceError):
        output.steps = []
