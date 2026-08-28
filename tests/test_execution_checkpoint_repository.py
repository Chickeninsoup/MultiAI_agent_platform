from __future__ import annotations

from pathlib import Path

import pytest

from src.execution_checkpoint import ExecutionCheckpoint
from src.execution_checkpoint_repository import (
    ExecutionCheckpointRepository,
)
from src.execution_failure import ExecutionFailure, FailureCategory
from src.step_execution_result import StepExecutionResult, StepStatus


def _checkpoint(task_id: str) -> ExecutionCheckpoint:
    return ExecutionCheckpoint(
        task_id=task_id,
        plan_id="plan-1",
        completed_step_ids=("step-a", "step-b"),
        step_results=(
            StepExecutionResult(
                step_id="step-a", status=StepStatus.SUCCESS, output="ok"
            ),
            StepExecutionResult(
                step_id="step-b", status=StepStatus.SUCCESS, output="ok"
            ),
            StepExecutionResult(
                step_id="step-c",
                status=StepStatus.FAILED,
                error="permission denied",
                failure=ExecutionFailure(
                    category=FailureCategory.BLOCKED,
                    message="permission denied",
                    step_id="step-c",
                ),
            ),
        ),
        blocked_step_id="step-c",
    )


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    repository = ExecutionCheckpointRepository(tmp_path)
    checkpoint = _checkpoint("task-a")

    repository.save(checkpoint)
    loaded = repository.load("task-a")

    assert loaded == checkpoint


def test_load_missing_checkpoint_raises(tmp_path: Path) -> None:
    repository = ExecutionCheckpointRepository(tmp_path)

    with pytest.raises(FileNotFoundError):
        repository.load("unknown")


def test_tasks_do_not_overwrite_each_other(tmp_path: Path) -> None:
    repository = ExecutionCheckpointRepository(tmp_path)
    checkpoint_a = _checkpoint("task-a")
    checkpoint_b = _checkpoint("task-b")

    repository.save(checkpoint_a)
    repository.save(checkpoint_b)

    assert repository.load("task-a") == checkpoint_a
    assert repository.load("task-b") == checkpoint_b


def test_delete_removes_the_checkpoint(tmp_path: Path) -> None:
    repository = ExecutionCheckpointRepository(tmp_path)
    repository.save(_checkpoint("task-a"))

    repository.delete("task-a")

    with pytest.raises(FileNotFoundError):
        repository.load("task-a")


def test_delete_is_idempotent_for_a_missing_checkpoint(
    tmp_path: Path,
) -> None:
    repository = ExecutionCheckpointRepository(tmp_path)

    repository.delete("unknown")
