from __future__ import annotations

from pathlib import Path

from src.repositories import JsonRepository
from src.run_continuation_checkpoint import RunContinuationCheckpoint
from src.run_continuation_checkpoint_errors import (
    MismatchedCheckpointError,
)


class RunContinuationCheckpointRepository:
    """Persists RunContinuationCheckpoints under
    tasks/<task_id>/runs/<run_id>/checkpoint.json (5E-5D-4C) - the
    same tasks/<task_id>/runs/<run_id>/ directory RunRepository
    already owns (run.json, events.jsonl, change_snapshot.json live
    there), one level deeper than ExecutionCheckpointRepository's
    tasks/<task_id>/checkpoint.json (a Task-scoped checkpoint for a
    different execution stack - see RunContinuationCheckpoint's own
    docstring). Reuses the filename "checkpoint.json" at this deeper
    scope rather than inventing a new name, matching
    ExecutionCheckpointRepository's own naming; the two never collide
    since they live at different path depths.

    Independently derives its path from tasks_dir rather than
    depending on RunRepository for it - the established convention in
    this codebase (ExecutionCheckpointRepository does the same rather
    than depending on TaskRepository): every repository here takes
    tasks_dir directly and owns its own path construction.

    save() derives the path from the checkpoint's own task_id/run_id
    (matching ExecutionCheckpointRepository.save(checkpoint), which
    derives its path from checkpoint.task_id) - there is no way for a
    caller to pass a checkpoint to a mismatched path.

    load(task_id, run_id) takes explicit key arguments (matching
    ExecutionCheckpointRepository.load(task_id)) and, after loading,
    verifies the loaded payload's own task_id/run_id agree with what
    was asked for - defending against a checkpoint file that was
    manually moved/copied to the wrong location, which the path alone
    cannot detect. Raises FileNotFoundError for a missing checkpoint
    (matching ExecutionCheckpointRepository/RuntimeApprovalRepository's
    raising convention - a checkpoint that should exist but doesn't is
    a caller error worth surfacing), and MismatchedCheckpointError for
    a found-but-wrong-identity one.
    """

    def __init__(self, tasks_dir: Path) -> None:
        self._tasks_dir = tasks_dir

    def get_checkpoint_file(self, task_id: str, run_id: str) -> Path:
        return (
            self._tasks_dir
            / task_id
            / "runs"
            / run_id
            / "checkpoint.json"
        )

    def save(self, checkpoint: RunContinuationCheckpoint) -> None:
        JsonRepository.save(
            self.get_checkpoint_file(
                checkpoint.task_id, checkpoint.run_id
            ),
            checkpoint.to_dict(),
        )

    def load(
        self, task_id: str, run_id: str
    ) -> RunContinuationCheckpoint:
        data = JsonRepository.load(
            self.get_checkpoint_file(task_id, run_id)
        )
        checkpoint = RunContinuationCheckpoint.from_dict(data)

        if (
            checkpoint.task_id != task_id
            or checkpoint.run_id != run_id
        ):
            raise MismatchedCheckpointError(
                f"Checkpoint at {task_id!r}/{run_id!r} contains "
                f"identifiers task_id={checkpoint.task_id!r}, "
                f"run_id={checkpoint.run_id!r} - refusing to load a "
                "checkpoint that does not match the location it was "
                "read from"
            )

        return checkpoint

    def delete(self, task_id: str, run_id: str) -> None:
        self.get_checkpoint_file(task_id, run_id).unlink(
            missing_ok=True
        )
