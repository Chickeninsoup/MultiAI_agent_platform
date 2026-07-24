import json
from pathlib import Path

from src.review.change_snapshot_builder import ChangeSnapshotBuilder


def _write_events(
    run_directory: Path,
    events: list[dict],
) -> None:
    run_directory.mkdir(parents=True, exist_ok=True)
    events_path = run_directory / "events.jsonl"
    events_path.write_text(
        "\n".join(json.dumps(event) for event in events) + "\n",
        encoding="utf-8",
    )


def test_reads_changed_file_from_mutation_event(
    tmp_path: Path,
) -> None:
    run_directory = tmp_path / "run-001"
    _write_events(
        run_directory,
        [
            {
                "type": "file_mutation",
                "operation": "patch",
                "path": "a.py",
            },
        ],
    )

    snapshot = ChangeSnapshotBuilder().build(
        run_id="run-001",
        run_directory=run_directory,
        repository_root=tmp_path,
    )

    assert snapshot.changed_files == ["a.py"]
    assert snapshot.mutation_count == 1


def test_deduplicates_repeated_file_mutations(
    tmp_path: Path,
) -> None:
    run_directory = tmp_path / "run-002"
    _write_events(
        run_directory,
        [
            {"type": "file_mutation", "path": "a.py"},
            {"type": "file_mutation", "path": "a.py"},
            {"type": "file_mutation", "path": "b.py"},
        ],
    )

    snapshot = ChangeSnapshotBuilder().build(
        run_id="run-002",
        run_directory=run_directory,
        repository_root=tmp_path,
    )

    assert snapshot.changed_files == ["a.py", "b.py"]
    # mutation_count counts every mutation event, not unique files
    assert snapshot.mutation_count == 3


def test_reads_run_test_result(tmp_path: Path) -> None:
    run_directory = tmp_path / "run-003"
    _write_events(
        run_directory,
        [
            {
                "type": "tool_result",
                "name": "run_test",
                "success": True,
                "exit_code": 0,
                "timed_out": False,
            },
        ],
    )

    snapshot = ChangeSnapshotBuilder().build(
        run_id="run-003",
        run_directory=run_directory,
        repository_root=tmp_path,
    )

    assert snapshot.test_results == {
        "run_test": {
            "exit_code": 0,
            "timed_out": False,
        }
    }


def test_last_run_test_result_wins_when_called_more_than_once(
    tmp_path: Path,
) -> None:
    run_directory = tmp_path / "run-004"
    _write_events(
        run_directory,
        [
            {
                "type": "tool_result",
                "name": "run_test",
                "success": True,
                "exit_code": 1,
                "timed_out": False,
            },
            {
                "type": "tool_result",
                "name": "run_test",
                "success": True,
                "exit_code": 0,
                "timed_out": False,
            },
        ],
    )

    snapshot = ChangeSnapshotBuilder().build(
        run_id="run-004",
        run_directory=run_directory,
        repository_root=tmp_path,
    )

    assert snapshot.test_results["run_test"]["exit_code"] == 0


def test_ignores_tool_results_from_other_tools(
    tmp_path: Path,
) -> None:
    run_directory = tmp_path / "run-005"
    _write_events(
        run_directory,
        [
            {
                "type": "tool_result",
                "name": "read_file",
                "success": True,
            },
        ],
    )

    snapshot = ChangeSnapshotBuilder().build(
        run_id="run-005",
        run_directory=run_directory,
        repository_root=tmp_path,
    )

    assert snapshot.test_results == {}


def test_no_mutations_produces_empty_snapshot(
    tmp_path: Path,
) -> None:
    run_directory = tmp_path / "run-006"
    _write_events(
        run_directory,
        [
            {
                "type": "tool_call",
                "name": "read_file",
                "input": {"path": "a.py"},
            },
        ],
    )

    snapshot = ChangeSnapshotBuilder().build(
        run_id="run-006",
        run_directory=run_directory,
        repository_root=tmp_path,
    )

    assert snapshot.changed_files == []
    assert snapshot.mutation_count == 0
    assert snapshot.test_results == {}
    assert snapshot.diff_path is None


def test_missing_events_file_produces_empty_snapshot(
    tmp_path: Path,
) -> None:
    run_directory = tmp_path / "run-007"
    run_directory.mkdir()

    snapshot = ChangeSnapshotBuilder().build(
        run_id="run-007",
        run_directory=run_directory,
        repository_root=tmp_path,
    )

    assert snapshot.changed_files == []
    assert snapshot.mutation_count == 0
    assert snapshot.test_results == {}
    assert snapshot.diff_path is None


def test_diff_path_set_when_diff_file_exists(
    tmp_path: Path,
) -> None:
    run_directory = tmp_path / "run-008"
    _write_events(run_directory, [])
    diff_file = run_directory / "diff.patch"
    diff_file.write_text("diff --git a/x b/x\n", encoding="utf-8")

    snapshot = ChangeSnapshotBuilder().build(
        run_id="run-008",
        run_directory=run_directory,
        repository_root=tmp_path,
    )

    assert snapshot.diff_path == str(diff_file)


def test_real_run_test_loop_events_produce_expected_snapshot() -> None:
    # tasks/task-run-test-loop/runs/run-001/events.jsonl predates the
    # exit_code/timed_out fields being added to the tool_result event
    # (this same change), so its run_test result has no exit_code —
    # this only checks the file-mutation side, which is unaffected.
    project_root = Path(__file__).resolve().parent.parent.parent
    run_directory = (
        project_root
        / "tasks"
        / "task-run-test-loop"
        / "runs"
        / "run-001"
    )

    snapshot = ChangeSnapshotBuilder().build(
        run_id="run-001",
        run_directory=run_directory,
        repository_root=project_root,
    )

    assert snapshot.changed_files == ["sandbox/calculator.py"]
    assert snapshot.mutation_count == 1
    assert "run_test" in snapshot.test_results
