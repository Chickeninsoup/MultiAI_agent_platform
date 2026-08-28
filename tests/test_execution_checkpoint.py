from __future__ import annotations

import dataclasses

import pytest

from src.execution_checkpoint import ExecutionCheckpoint
from src.step_execution_result import StepExecutionResult, StepStatus


def _result(step_id: str, status: StepStatus) -> StepExecutionResult:
    return StepExecutionResult(step_id=step_id, status=status)


def test_basic_construction() -> None:
    checkpoint = ExecutionCheckpoint(
        task_id="task-1",
        plan_id="plan-1",
        completed_step_ids=("step-a", "step-b"),
        step_results=(
            _result("step-a", StepStatus.SUCCESS),
            _result("step-b", StepStatus.SUCCESS),
        ),
        blocked_step_id="step-c",
    )

    assert checkpoint.task_id == "task-1"
    assert checkpoint.plan_id == "plan-1"


def test_preserves_step_ordering() -> None:
    results = (
        _result("step-a", StepStatus.SUCCESS),
        _result("step-b", StepStatus.SUCCESS),
        _result("step-c", StepStatus.FAILED),
    )

    checkpoint = ExecutionCheckpoint(
        task_id="task-1",
        plan_id="plan-1",
        completed_step_ids=("step-a", "step-b"),
        step_results=results,
        blocked_step_id="step-c",
    )

    assert [r.step_id for r in checkpoint.step_results] == [
        "step-a",
        "step-b",
        "step-c",
    ]
    assert checkpoint.completed_step_ids == ("step-a", "step-b")


def test_checkpoint_is_immutable() -> None:
    checkpoint = ExecutionCheckpoint(
        task_id="task-1",
        plan_id="plan-1",
        completed_step_ids=("step-a",),
        step_results=(_result("step-a", StepStatus.SUCCESS),),
        blocked_step_id=None,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        checkpoint.completed_step_ids = ()


def test_blocked_step_id_can_be_none_for_a_plain_pause() -> None:
    checkpoint = ExecutionCheckpoint(
        task_id="task-1",
        plan_id="plan-1",
        completed_step_ids=("step-a", "step-b"),
        step_results=(
            _result("step-a", StepStatus.SUCCESS),
            _result("step-b", StepStatus.SUCCESS),
        ),
        blocked_step_id=None,
    )

    assert checkpoint.blocked_step_id is None
