from __future__ import annotations

import dataclasses

import pytest

from src.task_plan import TaskPlan, TaskStep


def test_task_step_holds_step_id_agent_id_and_description() -> None:
    step = TaskStep(
        step_id="step-1",
        agent_id="agent-coder",
        description="implement feature",
    )

    assert step.step_id == "step-1"
    assert step.agent_id == "agent-coder"
    assert step.description == "implement feature"


def test_task_step_defaults_depends_on_to_empty_list() -> None:
    step = TaskStep(
        step_id="step-1",
        agent_id="agent-coder",
        description="implement feature",
    )

    assert step.depends_on == []


def test_task_step_can_declare_dependencies() -> None:
    step = TaskStep(
        step_id="step-2",
        agent_id="agent-coder",
        description="implement feature",
        depends_on=["step-1"],
    )

    assert step.depends_on == ["step-1"]


def test_task_step_is_frozen() -> None:
    step = TaskStep(
        step_id="step-1",
        agent_id="agent-coder",
        description="implement feature",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        step.agent_id = "agent-general"


def test_task_plan_holds_task_id_and_steps() -> None:
    step = TaskStep(
        step_id="step-1",
        agent_id="agent-coder",
        description="implement feature",
    )

    plan = TaskPlan(task_id="task-001", steps=[step])

    assert plan.task_id == "task-001"
    assert plan.steps == [step]


def test_task_plan_can_hold_multiple_ordered_steps() -> None:
    step_1 = TaskStep(
        step_id="step-1",
        agent_id="agent-researcher",
        description="find useful APIs",
    )
    step_2 = TaskStep(
        step_id="step-2",
        agent_id="agent-coder",
        description="implement scraper",
    )

    plan = TaskPlan(task_id="task-001", steps=[step_1, step_2])

    assert plan.steps == [step_1, step_2]


def test_task_plan_is_frozen() -> None:
    plan = TaskPlan(task_id="task-001", steps=[])

    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.task_id = "task-002"


def test_task_plan_round_trips_through_dict() -> None:
    plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="research",
                agent_id="agent-researcher",
                description="find useful APIs",
            ),
            TaskStep(
                step_id="coding",
                agent_id="agent-coder",
                description="implement API",
                depends_on=["research"],
            ),
        ],
    )

    restored = TaskPlan.from_dict(plan.to_dict())

    assert restored == plan
