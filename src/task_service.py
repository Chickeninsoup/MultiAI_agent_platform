from __future__ import annotations

from src.clock import utc_now
from src.models import RunDefinition, TaskDefinition
from src.repositories import RunRepository, TaskRepository, TextRepository


class TaskAlreadyExistsError(Exception):
    error_code = "TASK_ALREADY_EXISTS"


class TaskService:
    """Programmatically creates a new Task and its first Run.

    Every Task/Run in this repository so far has been hand-authored
    JSON (see README's "已知限制") - this is the first code path that
    constructs them from scratch. Deliberately narrow: only creates a
    brand-new Task (rejects an existing task_id rather than silently
    reusing it) with exactly one Run ("run-001") under it, and does
    not execute anything - callers still go through RunService.execute()
    to actually run it, so the existing state machine/review workflow
    is untouched.
    """

    FIRST_RUN_ID = "run-001"

    def __init__(
        self,
        *,
        task_repository: TaskRepository,
        run_repository: RunRepository,
    ) -> None:
        self._task_repository = task_repository
        self._run_repository = run_repository

    def create_task_and_run(
        self,
        *,
        task_id: str,
        title: str,
        description: str,
        agent_id: str,
        input_text: str,
        created_by: str,
        workspace_id: str = "workspace-main",
        priority: str = "normal",
        completion_criteria: list[str] | None = None,
        tags: list[str] | None = None,
    ) -> tuple[TaskDefinition, RunDefinition]:
        if self._task_repository.get_task_file(task_id).exists():
            raise TaskAlreadyExistsError(
                f"Task already exists: {task_id}"
            )

        now = utc_now()

        task = TaskDefinition(
            id=task_id,
            title=title,
            description=description,
            workspace_id=workspace_id,
            status="in_progress",
            priority=priority,
            created_by=created_by,
            assigned_agents=[agent_id],
            created_at=now,
            updated_at=now,
            started_at=now,
            completed_at=None,
            abandoned_at=None,
            current_run_id=self.FIRST_RUN_ID,
            run_count=1,
            completion_criteria=completion_criteria or [],
            tags=tags or [],
        )

        run = RunDefinition(
            id=self.FIRST_RUN_ID,
            task_id=task_id,
            agent_id=agent_id,
            status="in_progress",
            created_at=now,
            updated_at=now,
            started_at=now,
            completed_at=None,
        )

        self._task_repository.save(task)
        self._run_repository.save(run)
        self._run_repository.write_input(
            task_id,
            run.id,
            input_text,
        )
        TextRepository.write(
            self._task_repository.get_background_file(task_id),
            f"# Task Background\n\n{description}\n",
        )

        return task, run
