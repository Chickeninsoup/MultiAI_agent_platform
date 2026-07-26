import pytest

from src.domain.events.run_event import RunEvent


def test_run_event_creation() -> None:
    event = RunEvent(
        event_type="tool_call",
        timestamp=None,
        run_id="run-001",
        data={"name": "read_file"},
    )

    assert event.event_type == "tool_call"
    assert event.timestamp is None
    assert event.run_id == "run-001"
    assert event.data == {"name": "read_file"}


def test_run_event_accepts_a_timestamp() -> None:
    event = RunEvent(
        event_type="tool_result",
        timestamp="2026-07-26T10:01:00Z",
        run_id="run-001",
        data={"success": True},
    )

    assert event.timestamp == "2026-07-26T10:01:00Z"


def test_run_event_data_holds_arbitrary_event_shape() -> None:
    event = RunEvent(
        event_type="file_mutation",
        timestamp=None,
        run_id="run-030",
        data={
            "operation": "patch",
            "path": "src/main.py",
            "after_sha256": "abc123",
        },
    )

    assert event.data["operation"] == "patch"
    assert event.data["path"] == "src/main.py"
    assert event.data["after_sha256"] == "abc123"


def test_run_event_is_frozen() -> None:
    event = RunEvent(
        event_type="tool_result",
        timestamp=None,
        run_id="run-001",
        data={},
    )

    with pytest.raises(AttributeError):
        event.event_type = "changed"  # type: ignore[misc]
