from __future__ import annotations

from dataclasses import replace

from src.clock import utc_now
from src.planning.plan_execution_result import PlanExecutionResult
from src.planning.task_completion_errors import (
    TaskCompletionStateError,
    TaskNotFoundForCompletionError,
)
from src.repositories import TaskRepository


class TaskCompletionService:
    """Transitions a Task to completed once its plan has succeeded.

    First writer of TaskDefinition.status other than TaskService
    (5E-4C-2) - execution succeeding is the only signal this
    listens to. Does nothing on a failed/skipped execution: the Task
    simply stays in_progress, so resume/retry still see the team and
    state they left behind. Only in_progress -> completed is
    supported so far; failed/cancelled/abandoned terminal states are
    deliberately out of scope until a later stage decides those
    semantics.
    """

    def __init__(self, task_repository: TaskRepository) -> None:
        self._task_repository = task_repository

    def complete_if_successful(
        self, task_id: str, execution_result: PlanExecutionResult
    ) -> bool:
        if not execution_result.succeeded:
            return False

        try:
            task = self._task_repository.load(task_id)
        except FileNotFoundError as exc:
            raise TaskNotFoundForCompletionError(
                f"Task not found for completion: {task_id}"
            ) from exc

        if task.status == "completed":
            return True

        if task.status != "in_progress":
            raise TaskCompletionStateError(
                f"Cannot complete task {task_id} "
                f"from status {task.status}"
            )

        completed_at = utc_now()

        updated_task = replace(
            task,
            status="completed",
            completed_at=completed_at,
            updated_at=completed_at,
        )

        self._task_repository.save(updated_task)

        return True
