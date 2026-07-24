from pathlib import Path

import pytest

from src.review.change_snapshot import ChangeSnapshot
from src.review.snapshot_repository import (
    SnapshotNotFoundError,
    SnapshotRepository,
)


def test_save_then_load_round_trips(tmp_path: Path) -> None:
    run_directory = tmp_path / "run-001"
    run_directory.mkdir()

    snapshot = ChangeSnapshot(
        run_id="run-001",
        changed_files=["src/main.py", "tests/test_main.py"],
        mutation_count=3,
        test_results={
            "run_test": {"exit_code": 0, "timed_out": False},
        },
        diff_path=None,
    )

    repository = SnapshotRepository()
    repository.save(run_directory, snapshot)

    loaded = repository.load(run_directory)

    assert loaded == snapshot


def test_save_creates_missing_parent_directories(
    tmp_path: Path,
) -> None:
    run_directory = tmp_path / "nested" / "run-001"

    snapshot = ChangeSnapshot(
        run_id="run-001",
        changed_files=[],
        mutation_count=0,
        test_results={},
        diff_path=None,
    )

    repository = SnapshotRepository()
    repository.save(run_directory, snapshot)

    assert repository.get_snapshot_file(run_directory).exists()


def test_load_raises_when_snapshot_missing(
    tmp_path: Path,
) -> None:
    run_directory = tmp_path / "run-002"
    run_directory.mkdir()

    with pytest.raises(SnapshotNotFoundError):
        SnapshotRepository().load(run_directory)


def test_get_snapshot_file_path(tmp_path: Path) -> None:
    run_directory = tmp_path / "run-003"

    assert SnapshotRepository().get_snapshot_file(
        run_directory
    ) == run_directory / "change_snapshot.json"
