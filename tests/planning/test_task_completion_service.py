from __future__ import annotations

import pytest

from src.models import TaskDefinition
from src.planning.plan_execution_result import PlanExecutionResult
from src.planning.task_completion_errors import (
    TaskCompletionStateError,
    TaskNotFoundForCompletionError,
)
from src.planning.task_completion_service import TaskCompletionService
from src.step_execution_result import StepExecutionResult, StepStatus


class FakeTaskRepository:
    def __init__(self, task: TaskDefinition) -> None:
        self._tasks: dict[str, TaskDefinition] = {task.id: task}
        self.save_calls = 0
        self.load_calls = 0

    def load(self, task_id: str) -> TaskDefinition:
        self.load_calls += 1

        if task_id not in self._tasks:
            raise FileNotFoundError(task_id)

        return self._tasks[task_id]

    def save(self, task: TaskDefinition) -> None:
        self._tasks[task.id] = task
        self.save_calls += 1


def _task(status: str = "in_progress") -> TaskDefinition:
    return TaskDefinition(
        id="task-1",
        title="Build a feature",
        description="Implement the requested feature",
        workspace_id="workspace-main",
        status=status,
        priority="normal",
        created_by="user-1",
        assigned_agents=["agent-coder"],
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        started_at="2026-01-01T00:00:00Z",
        completed_at=None,
        abandoned_at=None,
        current_run_id="run-001",
        run_count=1,
        completion_criteria=[],
        tags=[],
    )


def _successful_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="coding",
                status=StepStatus.SUCCESS,
                output="done",
            )
        ]
    )


def _failed_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="coding",
                status=StepStatus.FAILED,
                error="boom",
            )
        ]
    )


def _skipped_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="coding",
                status=StepStatus.SKIPPED,
                error="dependency failed",
            )
        ]
    )


def test_successful_execution_completes_the_task() -> None:
    repository = FakeTaskRepository(_task())
    service = TaskCompletionService(repository)

    completed = service.complete_if_successful(
        "task-1", _successful_result()
    )

    assert completed is True
    task = repository.load("task-1")
    assert task.status == "completed"
    assert task.completed_at is not None


def test_successful_execution_updates_updated_at_to_completed_at() -> (
    None
):
    repository = FakeTaskRepository(_task())
    service = TaskCompletionService(repository)

    service.complete_if_successful("task-1", _successful_result())

    task = repository.load("task-1")
    assert task.updated_at == task.completed_at


def test_failed_execution_does_not_complete_the_task() -> None:
    repository = FakeTaskRepository(_task())
    service = TaskCompletionService(repository)

    completed = service.complete_if_successful(
        "task-1", _failed_result()
    )

    assert completed is False
    task = repository.load("task-1")
    assert task.status == "in_progress"
    assert task.completed_at is None


def test_skipped_step_does_not_complete_the_task() -> None:
    repository = FakeTaskRepository(_task())
    service = TaskCompletionService(repository)

    completed = service.complete_if_successful(
        "task-1", _skipped_result()
    )

    assert completed is False
    task = repository.load("task-1")
    assert task.status == "in_progress"
    assert task.completed_at is None


def test_successful_completion_preserves_other_task_fields() -> None:
    original = _task()
    repository = FakeTaskRepository(original)
    service = TaskCompletionService(repository)

    service.complete_if_successful("task-1", _successful_result())

    task = repository.load("task-1")
    assert task.id == original.id
    assert task.title == original.title
    assert task.description == original.description
    assert task.assigned_agents == original.assigned_agents
    assert task.created_at == original.created_at


def test_completed_task_is_idempotent() -> None:
    repository = FakeTaskRepository(_task())
    service = TaskCompletionService(repository)
    service.complete_if_successful("task-1", _successful_result())
    first_completed_at = repository.load("task-1").completed_at
    save_calls_after_first_completion = repository.save_calls

    result = service.complete_if_successful(
        "task-1", _successful_result()
    )

    assert result is True
    task = repository.load("task-1")
    assert task.completed_at == first_completed_at
    assert repository.save_calls == save_calls_after_first_completion


def test_unknown_task_raises_task_not_found_for_completion() -> None:
    repository = FakeTaskRepository(_task())
    service = TaskCompletionService(repository)

    with pytest.raises(TaskNotFoundForCompletionError):
        service.complete_if_successful(
            "missing-task", _successful_result()
        )

    assert repository.save_calls == 0


def test_failed_execution_for_missing_task_returns_false() -> None:
    repository = FakeTaskRepository(_task())
    service = TaskCompletionService(repository)

    completed = service.complete_if_successful(
        "missing-task", _failed_result()
    )

    assert completed is False
    assert repository.save_calls == 0
    assert repository.load_calls == 0


def test_abandoned_task_cannot_be_completed() -> None:
    repository = FakeTaskRepository(_task(status="abandoned"))
    service = TaskCompletionService(repository)
    before = repository.save_calls

    with pytest.raises(TaskCompletionStateError):
        service.complete_if_successful("task-1", _successful_result())

    assert repository.save_calls == before
    task = repository.load("task-1")
    assert task.status == "abandoned"
    assert task.completed_at is None


def test_other_non_in_progress_status_cannot_be_completed() -> None:
    repository = FakeTaskRepository(_task(status="failed"))
    service = TaskCompletionService(repository)
    before = repository.save_calls

    with pytest.raises(TaskCompletionStateError):
        service.complete_if_successful("task-1", _successful_result())

    assert repository.save_calls == before
    task = repository.load("task-1")
    assert task.status == "failed"
    assert task.completed_at is None
