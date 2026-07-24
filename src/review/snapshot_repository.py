from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from src.review.change_snapshot import ChangeSnapshot


class SnapshotNotFoundError(Exception):
    error_code = "SNAPSHOT_NOT_FOUND"


class SnapshotRepository:
    """Persists a ChangeSnapshot alongside a Run's own files.

    Deliberately takes the run's directory directly rather than
    resolving task_id/run_id itself - RunService already has the run
    directory in hand when it builds the snapshot, and callers that
    only have a run_id (e.g. a future `review` CLI command) resolve
    the directory the same way RunService/RunRepository already do.
    """

    SNAPSHOT_FILE_NAME = "change_snapshot.json"

    def get_snapshot_file(self, run_directory: Path) -> Path:
        return run_directory / self.SNAPSHOT_FILE_NAME

    def save(
        self,
        run_directory: Path,
        snapshot: ChangeSnapshot,
    ) -> None:
        snapshot_path = self.get_snapshot_file(run_directory)
        snapshot_path.parent.mkdir(parents=True, exist_ok=True)
        snapshot_path.write_text(
            json.dumps(asdict(snapshot)),
            encoding="utf-8",
        )

    def load(self, run_directory: Path) -> ChangeSnapshot:
        snapshot_path = self.get_snapshot_file(run_directory)

        if not snapshot_path.exists():
            raise SnapshotNotFoundError(
                f"No change snapshot found at: {snapshot_path}"
            )

        data = json.loads(
            snapshot_path.read_text(encoding="utf-8")
        )

        return ChangeSnapshot(**data)
