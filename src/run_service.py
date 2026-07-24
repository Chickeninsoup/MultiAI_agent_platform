from dataclasses import dataclass, replace
from datetime import datetime, timezone
from pathlib import Path

from src.context_builder import RunContextBuilder
from src.execution import RunExecutor
from src.models import RunDefinition, TaskDefinition
from src.repositories import (
    AgentRepository,
    RunRepository,
    TaskRepository,
)
from src.review.change_snapshot_builder import ChangeSnapshotBuilder
from src.review.review_policy import requires_review
from src.review.snapshot_repository import SnapshotRepository
from src.run_errors import RunErrorCategory, classify_error, is_retryable

RESUMABLE_STATUSES = {"in_progress", "interrupted"}


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


@dataclass(frozen=True)
class RunServiceResult:
    task_id: str
    run_id: str
    agent_id: str
    status: str
    output_path: Path
    summary_path: Path
    events_path: Path
    llm_rounds: int | None = None
    tool_rounds: int | None = None
    tool_calls: int | None = None
    total_input_tokens: int | None = None
    total_output_tokens: int | None = None


class RunExecutionFailedError(RuntimeError):
    """Raised when the underlying executor fails mid-run.

    Carries enough context (run/agent id, the run's new persisted
    status, its error category/retryability, and where its partial
    event log lives) for the caller to report a useful failure summary
    and decide whether `resume` is worth trying.
    """

    def __init__(
        self,
        *,
        task_id: str,
        run_id: str,
        agent_id: str,
        status: str,
        category: RunErrorCategory,
        retryable: bool,
        events_path: Path,
        original_error: Exception,
    ) -> None:
        super().__init__(str(original_error))
        self.task_id = task_id
        self.run_id = run_id
        self.agent_id = agent_id
        self.status = status
        self.category = category
        self.retryable = retryable
        self.events_path = events_path
        self.original_error = original_error


class RunService:
    """Coordinate validation, execution, and persistence."""

    def __init__(
        self,
        task_repository: TaskRepository,
        run_repository: RunRepository,
        agent_repository: AgentRepository,
        context_builder: RunContextBuilder,
        executor: RunExecutor,
        project_root: Path,
    ) -> None:
        self._task_repository = task_repository
        self._run_repository = run_repository
        self._agent_repository = agent_repository
        self._context_builder = context_builder
        self._executor = executor
        self._project_root = project_root
        self._change_snapshot_builder = ChangeSnapshotBuilder()
        self._snapshot_repository = SnapshotRepository()

    def execute(self, task_id: str) -> RunServiceResult:
        task = self._task_repository.load(task_id)
        run_id = task.current_run_id

        if not run_id:
            raise ValueError(
                f"Task {task_id} has no current_run_id"
            )

        run = self._run_repository.load(task.id, run_id)

        if run.status != "in_progress":
            if run.is_completed():
                raise ValueError(
                    f"Run {run.id} has already been completed"
                )

            raise ValueError(
                f"Run {run.id} has status '{run.status}' and cannot "
                f"be executed directly; use `resume {run.id}` to "
                "retry it as a new run."
            )

        if run.task_id != task.id:
            raise ValueError(
                f"Run {run.id} belongs to task "
                f"{run.task_id}, not {task.id}"
            )

        if not task.is_agent_assigned(run.agent_id):
            raise ValueError(
                f"Agent {run.agent_id} is not assigned "
                f"to task {task.id}"
            )

        agent = self._agent_repository.load(run.agent_id)

        if agent.status != "ready":
            raise ValueError(
                f"Agent {agent.id} is not ready"
            )

        context = self._context_builder.build(
            task=task,
            run=run,
            agent=agent,
        )

        try:
            result = self._executor.execute(context)
        except Exception as error:
            raise self._fail_run(
                task=task,
                run=run,
                error=error,
            ) from error

        self._run_repository.write_output(
            task.id,
            run.id,
            result.output_markdown,
        )

        self._run_repository.write_summary(
            task.id,
            run.id,
            result.summary_markdown,
        )

        run_directory = self._run_repository.get_run_dir(
            task.id,
            run.id,
        )
        snapshot = self._change_snapshot_builder.build(
            run_id=run.id,
            run_directory=run_directory,
            repository_root=self._project_root,
        )
        # Persisted so `review` later shows the state as it was right
        # after this Run finished, not a live recomputation against
        # whatever the repository looks like at review time.
        self._snapshot_repository.save(run_directory, snapshot)

        review_required = requires_review(
            agent_id=agent.id,
            snapshot=snapshot,
        )

        completed_at = utc_now()

        finished_run = replace(
            run,
            status=(
                "awaiting_review"
                if review_required
                else "completed"
            ),
            updated_at=completed_at,
            completed_at=completed_at,
            metadata={
                **run.metadata,
                "review_required": review_required,
                "changed_files": snapshot.changed_files,
            },
        )

        updated_task = replace(
            task,
            updated_at=completed_at,
        )

        self._run_repository.save(finished_run)
        self._task_repository.save(updated_task)

        return RunServiceResult(
            task_id=task.id,
            run_id=run.id,
            agent_id=run.agent_id,
            status=finished_run.status,
            output_path=self._run_repository.get_output_file(
                task.id,
                run.id,
            ),
            summary_path=self._run_repository.get_summary_file(
                task.id,
                run.id,
            ),
            events_path=self._run_repository.get_events_file(
                task.id,
                run.id,
            ),
            llm_rounds=result.metadata.get("llm_rounds"),
            tool_rounds=result.metadata.get("tool_rounds"),
            tool_calls=result.metadata.get("tool_calls"),
            total_input_tokens=result.metadata.get(
                "total_input_tokens"
            ),
            total_output_tokens=result.metadata.get(
                "total_output_tokens"
            ),
        )

    def resume(self, run_id: str) -> RunServiceResult:
        """Retry a run that never reached a terminal state.

        Each Run represents a single execution attempt: resuming does
        not reuse the old run_id, it marks the old run `interrupted`
        (if a crashed process left it stuck on `in_progress`) and
        creates a brand new Run (`retry_of` pointing at the old one,
        reusing the same input.md) which is then actually executed.
        """
        task = self._find_task_for_run(run_id)

        if task is None:
            raise ValueError(f"No task owns run {run_id}")

        old_run = self._run_repository.load(task.id, run_id)

        if old_run.status not in RESUMABLE_STATUSES:
            raise ValueError(
                f"Run {run_id} has status '{old_run.status}' and "
                "cannot be resumed"
            )

        if old_run.status == "in_progress":
            # Still in_progress at resume time with no process
            # actually running it means execution was cut short
            # (crash / kill) before it could persist a terminal
            # status. Record that before creating the retry attempt.
            old_run = replace(
                old_run,
                status="interrupted",
                updated_at=utc_now(),
            )
            self._run_repository.save(old_run)

        new_run_id = self._next_run_id(task.id)
        created_at = utc_now()

        new_run = RunDefinition(
            id=new_run_id,
            task_id=task.id,
            agent_id=old_run.agent_id,
            status="in_progress",
            created_at=created_at,
            updated_at=created_at,
            started_at=created_at,
            completed_at=None,
            metadata={"retry_of": old_run.id},
        )
        self._run_repository.save(new_run)

        self._run_repository.write_input(
            task.id,
            new_run_id,
            self._run_repository.read_input(task.id, old_run.id),
        )

        updated_task = replace(
            task,
            current_run_id=new_run_id,
            run_count=task.run_count + 1,
            updated_at=created_at,
        )
        self._task_repository.save(updated_task)

        return self.execute(task.id)

    def get_run(
        self,
        run_id: str,
    ) -> tuple[TaskDefinition, RunDefinition]:
        task = self._find_task_for_run(run_id)

        if task is None:
            raise ValueError(f"No task owns run {run_id}")

        run = self._run_repository.load(task.id, run_id)

        return task, run

    def decide_review(
        self,
        run_id: str,
        *,
        approved: bool,
    ) -> RunDefinition:
        _task, run = self.get_run(run_id)

        if run.status != "awaiting_review":
            raise ValueError(
                f"Run {run_id} has status '{run.status}' and is "
                "not awaiting review."
            )

        decided_run = replace(
            run,
            status="approved" if approved else "rejected",
            updated_at=utc_now(),
        )
        self._run_repository.save(decided_run)

        return decided_run

    def _fail_run(
        self,
        *,
        task: TaskDefinition,
        run: RunDefinition,
        error: Exception,
    ) -> RunExecutionFailedError:
        category = classify_error(error)
        retryable = is_retryable(category)
        new_status = "interrupted" if retryable else "failed"
        failed_at = utc_now()

        failed_run = replace(
            run,
            status=new_status,
            updated_at=failed_at,
            metadata={
                **run.metadata,
                "error_category": category,
                "error_message": str(error),
                "retryable": retryable,
            },
        )
        self._run_repository.save(failed_run)

        return RunExecutionFailedError(
            task_id=task.id,
            run_id=run.id,
            agent_id=run.agent_id,
            status=new_status,
            category=category,
            retryable=retryable,
            events_path=self._run_repository.get_events_file(
                task.id,
                run.id,
            ),
            original_error=error,
        )

    def _find_task_for_run(
        self,
        run_id: str,
    ) -> TaskDefinition | None:
        for task in self._task_repository.list_all():
            if run_id in self._run_repository.list_run_ids(task.id):
                return task

        return None

    def _next_run_id(self, task_id: str) -> str:
        max_index = 0

        for existing_run_id in self._run_repository.list_run_ids(
            task_id
        ):
            prefix = "run-"

            if not existing_run_id.startswith(prefix):
                continue

            suffix = existing_run_id[len(prefix):]

            if suffix.isdigit():
                max_index = max(max_index, int(suffix))

        return f"run-{max_index + 1:03d}"
