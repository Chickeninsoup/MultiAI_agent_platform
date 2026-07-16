from dataclasses import replace
from datetime import datetime, timezone

from src.execution import RunExecutionContext, RunExecutor
from src.repositories import (
    AgentRepository,
    RunRepository,
    TaskRepository,
)


def utc_now() -> str:
    return (
        datetime.now(timezone.utc)
        .replace(microsecond=0)
        .isoformat()
        .replace("+00:00", "Z")
    )


class RunService:
    """Coordinate validation, execution, and persistence for one run."""

    def __init__(
        self,
        task_repository: TaskRepository,
        run_repository: RunRepository,
        agent_repository: AgentRepository,
        executor: RunExecutor,
    ) -> None:
        self._task_repository = task_repository
        self._run_repository = run_repository
        self._agent_repository = agent_repository
        self._executor = executor

    def execute(self, task_id: str) -> None:
        task = self._task_repository.load(task_id)
        run_id = task.current_run_id

        if not run_id:
            raise ValueError(
                f"Task {task_id} has no current_run_id"
            )

        run = self._run_repository.load(task_id, run_id)

        if run.is_completed():
            raise ValueError(
                f"Run {run_id} has already been completed"
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

        run_input = self._run_repository.read_input(
            task.id,
            run.id,
        )

        context = RunExecutionContext(
            task=task,
            run=run,
            agent=agent,
            run_input=run_input,
        )

        result = self._executor.execute(context)

        self._run_repository.write_output(
            task.id,
            run.id,
            result.output,
        )

        self._run_repository.write_summary(
            task.id,
            run.id,
            result.summary,
        )

        completed_at = utc_now()

        completed_run = replace(
            run,
            status="completed",
            updated_at=completed_at,
            completed_at=completed_at,
        )

        updated_task = replace(
            task,
            updated_at=completed_at,
        )

        self._run_repository.save(completed_run)
        self._task_repository.save(updated_task)

        output_file = self._run_repository.get_output_file(
            task.id,
            run.id,
        )

        print(f"Completed run: {run.id}")
        print(f"Output written to: {output_file}")
