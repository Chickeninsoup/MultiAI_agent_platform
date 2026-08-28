from __future__ import annotations

from pathlib import Path

from src.execution_checkpoint import ExecutionCheckpoint
from src.repositories import JsonRepository
from src.step_execution_result import StepExecutionResult


class ExecutionCheckpointRepository:
    """Persists ExecutionCheckpoints under tasks/<task_id>/checkpoint.json
    (5E-5C-8B) - the same tasks/<task_id>/ tree TaskRepository/
    PlanRepository/ApprovalRepository already use, not a separate
    top-level checkpoints/ tree.

    load() raises FileNotFoundError for an unknown task_id rather than
    returning None - matching TaskRepository/RunRepository/
    AgentRepository's load() convention (a checkpoint that should
    exist but doesn't is a caller error worth surfacing), not
    PlanRepository/ApprovalRepository's get()-returns-None convention
    (which fits "has this task ever been planned/approved," a
    legitimately common "no" case).
    """

    def __init__(self, tasks_dir: Path) -> None:
        self._tasks_dir = tasks_dir

    def get_checkpoint_file(self, task_id: str) -> Path:
        return self._tasks_dir / task_id / "checkpoint.json"

    def save(self, checkpoint: ExecutionCheckpoint) -> None:
        JsonRepository.save(
            self.get_checkpoint_file(checkpoint.task_id),
            {
                "task_id": checkpoint.task_id,
                "plan_id": checkpoint.plan_id,
                "completed_step_ids": list(
                    checkpoint.completed_step_ids
                ),
                "step_results": [
                    result.to_dict()
                    for result in checkpoint.step_results
                ],
                "blocked_step_id": checkpoint.blocked_step_id,
            },
        )

    def load(self, task_id: str) -> ExecutionCheckpoint:
        data = JsonRepository.load(self.get_checkpoint_file(task_id))

        return ExecutionCheckpoint(
            task_id=data["task_id"],
            plan_id=data["plan_id"],
            completed_step_ids=tuple(data["completed_step_ids"]),
            step_results=tuple(
                StepExecutionResult.from_dict(result_data)
                for result_data in data["step_results"]
            ),
            blocked_step_id=data.get("blocked_step_id"),
        )

    def delete(self, task_id: str) -> None:
        self.get_checkpoint_file(task_id).unlink(missing_ok=True)
