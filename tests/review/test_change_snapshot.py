import pytest

from src.review.change_snapshot import ChangeSnapshot


def test_creates_snapshot_with_expected_fields() -> None:
    snapshot = ChangeSnapshot(
        run_id="run-001",
        changed_files=["src/main.py"],
        mutation_count=1,
        test_results={
            "pytest": {
                "exit_code": 0,
            },
        },
        diff_path=None,
    )

    assert snapshot.run_id == "run-001"
    assert snapshot.mutation_count == 1
    assert snapshot.changed_files == ["src/main.py"]
    assert snapshot.test_results == {"pytest": {"exit_code": 0}}
    assert snapshot.diff_path is None


def test_supports_multiple_changed_files() -> None:
    snapshot = ChangeSnapshot(
        run_id="run-002",
        changed_files=[
            "src/calculator.py",
            "tests/test_calculator.py",
        ],
        mutation_count=2,
        test_results={"pytest": {"exit_code": 0}},
        diff_path="tasks/task-1/runs/run-002/diff.patch",
    )

    assert snapshot.changed_files == [
        "src/calculator.py",
        "tests/test_calculator.py",
    ]
    assert snapshot.diff_path == (
        "tasks/task-1/runs/run-002/diff.patch"
    )


def test_supports_no_changes() -> None:
    snapshot = ChangeSnapshot(
        run_id="run-003",
        changed_files=[],
        mutation_count=0,
        test_results={},
        diff_path=None,
    )

    assert snapshot.changed_files == []
    assert snapshot.mutation_count == 0


def test_snapshot_is_immutable() -> None:
    snapshot = ChangeSnapshot(
        run_id="run-001",
        changed_files=[],
        mutation_count=0,
        test_results={},
        diff_path=None,
    )

    with pytest.raises(AttributeError):
        snapshot.run_id = "run-999"  # type: ignore[misc]
