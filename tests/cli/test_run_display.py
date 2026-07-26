from src.cli.run_display import format_run_inspection, format_run_list
from src.domain.events.run_event import RunEvent
from src.domain.events.timeline import RunTimeline
from src.models import RunDefinition
from src.review.change_snapshot import ChangeSnapshot
from src.run_query_service import RunInspection


def _run(
    *,
    run_id: str = "run-001",
    task_id: str = "task-a",
    agent_id: str = "agent-coder",
    status: str = "completed",
    changed_files: list[str] | None = None,
) -> RunDefinition:
    return RunDefinition(
        id=run_id,
        task_id=task_id,
        agent_id=agent_id,
        status=status,
        created_at="2026-01-01T00:00:00Z",
        updated_at="2026-01-01T00:00:00Z",
        started_at="2026-01-01T00:00:00Z",
        completed_at="2026-01-01T00:00:00Z",
        metadata={"changed_files": changed_files or []},
    )


def test_format_run_list_handles_no_runs() -> None:
    assert format_run_list([]) == "No runs found."


def test_format_run_list_includes_key_fields() -> None:
    output = format_run_list(
        [
            _run(
                run_id="run-001",
                task_id="task-a",
                status="awaiting_review",
                changed_files=["src/main.py"],
            ),
        ]
    )

    assert "run-001" in output
    assert "task-a" in output
    assert "agent-coder" in output
    assert "awaiting_review" in output
    assert "1 file" in output


def test_format_run_list_pluralizes_change_count() -> None:
    output = format_run_list(
        [_run(changed_files=["a.py", "b.py"])]
    )

    assert "2 files" in output


def test_format_run_list_shows_zero_files_for_no_changes() -> None:
    output = format_run_list([_run(changed_files=[])])

    assert "0 files" in output


def test_format_run_list_lists_multiple_runs() -> None:
    output = format_run_list(
        [
            _run(run_id="run-001"),
            _run(run_id="run-002"),
        ]
    )

    assert "run-001" in output
    assert "run-002" in output


def _inspection(
    *,
    events: list[RunEvent] | None = None,
    snapshot: ChangeSnapshot | None = None,
    status: str = "awaiting_review",
) -> RunInspection:
    return RunInspection(
        run=_run(status=status),
        task_id="task-a",
        timeline=RunTimeline(run_id="run-001", events=events or []),
        snapshot=snapshot,
    )


def test_format_run_inspection_handles_empty_timeline() -> None:
    output = format_run_inspection(_inspection())

    assert "no events recorded" in output


def test_format_run_inspection_lists_timeline_events() -> None:
    events = [
        RunEvent(
            event_type="llm_response",
            timestamp=None,
            run_id="run-001",
            data={"round": 1},
        ),
        RunEvent(
            event_type="tool_call",
            timestamp=None,
            run_id="run-001",
            data={"name": "read_file"},
        ),
        RunEvent(
            event_type="tool_result",
            timestamp=None,
            run_id="run-001",
            data={"name": "read_file"},
        ),
        RunEvent(
            event_type="file_mutation",
            timestamp=None,
            run_id="run-001",
            data={"operation": "patch"},
        ),
    ]

    output = format_run_inspection(_inspection(events=events))

    assert "1. llm_response" in output
    assert "2. tool_call read_file" in output
    assert "3. tool_result read_file" in output
    assert "4. file_mutation patch" in output


def test_format_run_inspection_handles_missing_snapshot() -> None:
    output = format_run_inspection(_inspection(snapshot=None))

    assert "Changes:\n(none)" in output
    assert "Tests:\n(none)" in output


def test_format_run_inspection_shows_snapshot_changes_and_tests() -> None:
    snapshot = ChangeSnapshot(
        run_id="run-001",
        changed_files=["src/main.py"],
        mutation_count=1,
        test_results={"run_test": {"exit_code": 0}},
        diff_path=None,
    )

    output = format_run_inspection(_inspection(snapshot=snapshot))

    assert "- src/main.py" in output
    assert "run_test:" in output
    assert "exit_code: 0" in output
