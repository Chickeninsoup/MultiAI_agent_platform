import json
from pathlib import Path

from src.run_events import (
    InMemoryRunEventSink,
    JsonlRunEventSink,
    NullRunEventSink,
)


def test_in_memory_sink_collects_events() -> None:
    sink = InMemoryRunEventSink()

    sink.emit(
        {
            "type": "tool_call",
            "name": "read_file",
        }
    )

    assert sink.events == [
        {
            "type": "tool_call",
            "name": "read_file",
        }
    ]


def test_null_sink_drops_events() -> None:
    sink = NullRunEventSink()

    # Should not raise; there is nothing to observe afterwards.
    sink.emit({"type": "tool_call", "name": "read_file"})


def test_jsonl_sink_appends_valid_json_lines(
    tmp_path: Path,
) -> None:
    events_path = tmp_path / "events.jsonl"

    sink = JsonlRunEventSink(
        events_path,
        truncate_existing=True,
    )

    sink.emit(
        {
            "type": "llm_response",
            "round": 1,
        }
    )

    sink.emit(
        {
            "type": "tool_call",
            "name": "list_files",
        }
    )

    lines = events_path.read_text(
        encoding="utf-8"
    ).splitlines()

    assert len(lines) == 2

    assert json.loads(lines[0]) == {
        "type": "llm_response",
        "round": 1,
    }

    assert json.loads(lines[1]) == {
        "type": "tool_call",
        "name": "list_files",
    }


def test_jsonl_sink_preserves_unicode(
    tmp_path: Path,
) -> None:
    events_path = tmp_path / "events.jsonl"

    sink = JsonlRunEventSink(
        events_path,
        truncate_existing=True,
    )

    sink.emit(
        {
            "type": "message",
            "content": "中文测试",
        }
    )

    content = events_path.read_text(
        encoding="utf-8"
    )

    assert "中文测试" in content


def test_jsonl_sink_truncates_existing_file(
    tmp_path: Path,
) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        '{"type": "stale_event"}\n',
        encoding="utf-8",
    )

    sink = JsonlRunEventSink(
        events_path,
        truncate_existing=True,
    )

    sink.emit({"type": "fresh_event"})

    lines = events_path.read_text(
        encoding="utf-8"
    ).splitlines()

    assert len(lines) == 1
    assert json.loads(lines[0]) == {"type": "fresh_event"}


def test_jsonl_sink_appends_without_truncating_by_default(
    tmp_path: Path,
) -> None:
    events_path = tmp_path / "events.jsonl"
    events_path.write_text(
        '{"type": "previous_event"}\n',
        encoding="utf-8",
    )

    sink = JsonlRunEventSink(events_path)
    sink.emit({"type": "new_event"})

    lines = events_path.read_text(
        encoding="utf-8"
    ).splitlines()

    assert len(lines) == 2
