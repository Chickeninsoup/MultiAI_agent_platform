import json
from pathlib import Path

from src.domain.events.event_repository import EventRepository


def _write_events(path: Path, lines: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join(json.dumps(line) for line in lines) + "\n",
        encoding="utf-8",
    )


def test_loads_multiple_events_in_order(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(
        events_path,
        [
            {"type": "tool_call", "name": "read_file"},
            {"type": "tool_result", "name": "read_file", "success": True},
        ],
    )

    events = EventRepository().load_events(
        events_path,
        run_id="run-001",
    )

    assert [event.event_type for event in events] == [
        "tool_call",
        "tool_result",
    ]
    assert all(event.run_id == "run-001" for event in events)


def test_event_data_preserves_full_original_payload(
    tmp_path: Path,
) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(
        events_path,
        [
            {
                "type": "tool_call",
                "name": "read_file",
                "input": {"path": "a.py"},
            },
        ],
    )

    events = EventRepository().load_events(
        events_path,
        run_id="run-001",
    )

    assert events[0].data["name"] == "read_file"
    assert events[0].data["input"] == {"path": "a.py"}
    # the full raw payload is kept, not stripped down to a subset
    assert events[0].data == {
        "type": "tool_call",
        "name": "read_file",
        "input": {"path": "a.py"},
    }


def test_empty_file_returns_no_events(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text("", encoding="utf-8")

    events = EventRepository().load_events(
        events_path,
        run_id="run-001",
    )

    assert events == []


def test_missing_file_returns_no_events(tmp_path: Path) -> None:
    events_path = tmp_path / "does-not-exist.jsonl"

    events = EventRepository().load_events(
        events_path,
        run_id="run-001",
    )

    assert events == []


def test_missing_type_falls_back_to_unknown(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    _write_events(events_path, [{"name": "test"}])

    events = EventRepository().load_events(
        events_path,
        run_id="run-001",
    )

    assert events[0].event_type == "unknown"


def test_skips_blank_lines(tmp_path: Path) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        '{"type": "tool_call"}\n\n   \n{"type": "tool_result"}\n',
        encoding="utf-8",
    )

    events = EventRepository().load_events(
        events_path,
        run_id="run-001",
    )

    assert [event.event_type for event in events] == [
        "tool_call",
        "tool_result",
    ]


def test_loads_real_committed_events_file() -> None:
    project_root = Path(__file__).resolve().parent.parent.parent.parent
    events_path = (
        project_root
        / "tasks"
        / "task-patch-test"
        / "runs"
        / "run-001"
        / "events.jsonl"
    )

    events = EventRepository().load_events(
        events_path,
        run_id="run-001",
    )

    assert len(events) > 0
    assert all(event.run_id == "run-001" for event in events)
    assert any(
        event.event_type == "file_mutation" for event in events
    )
