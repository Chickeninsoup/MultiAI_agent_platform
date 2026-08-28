from __future__ import annotations

from pathlib import Path

from src.planning.plan_execution_result import PlanExecutionResult
from src.planning.task_completion_service import TaskCompletionService
from src.repositories import RunRepository, TaskRepository
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_service import TaskService


def _create_task(tmp_path: Path, task_id: str) -> TaskRepository:
    """Bootstraps a real, on-disk Task via TaskService - the same
    entry point production code uses - so this test exercises the
    real TaskRepository persistence boundary, not a fake."""

    task_repository = TaskRepository(tmp_path)
    run_repository = RunRepository(tmp_path)
    task_service = TaskService(
        task_repository=task_repository, run_repository=run_repository
    )
    task_service.create_task_and_run(
        task_id=task_id,
        title="Build a feature",
        description="Implement the requested feature",
        agent_id="agent-coder",
        input_text="implement the feature",
        created_by="user-1",
    )

    return task_repository


def _successful_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="coding", status=StepStatus.SUCCESS, output="done"
            )
        ]
    )


def _failed_result() -> PlanExecutionResult:
    return PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="coding", status=StepStatus.FAILED, error="boom"
            )
        ]
    )


def test_successful_execution_completes_the_task_on_disk(
    tmp_path: Path,
) -> None:
    task_repository = _create_task(tmp_path, "task-1")
    service = TaskCompletionService(task_repository)

    completed = service.complete_if_successful(
        "task-1", _successful_result()
    )

    assert completed is True
    task = task_repository.load("task-1")
    assert task.status == "completed"
    assert task.completed_at is not None


def test_failed_execution_leaves_the_task_in_progress_on_disk(
    tmp_path: Path,
) -> None:
    task_repository = _create_task(tmp_path, "task-1")
    service = TaskCompletionService(task_repository)

    completed = service.complete_if_successful(
        "task-1", _failed_result()
    )

    assert completed is False
    task = task_repository.load("task-1")
    assert task.status == "in_progress"
    assert task.completed_at is None
