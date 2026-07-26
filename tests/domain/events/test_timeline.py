import pytest

from src.domain.events.run_event import RunEvent
from src.domain.events.timeline import RunTimeline


def test_creates_timeline_with_events() -> None:
    events = [
        RunEvent(
            event_type="tool_call",
            timestamp=None,
            run_id="run-001",
            data={},
        ),
        RunEvent(
            event_type="tool_result",
            timestamp=None,
            run_id="run-001",
            data={},
        ),
    ]

    timeline = RunTimeline(run_id="run-001", events=events)

    assert timeline.run_id == "run-001"
    assert timeline.events == events


def test_supports_empty_timeline() -> None:
    timeline = RunTimeline(run_id="run-001", events=[])

    assert timeline.events == []


def test_timeline_is_frozen() -> None:
    timeline = RunTimeline(run_id="run-001", events=[])

    with pytest.raises(AttributeError):
        timeline.run_id = "run-999"  # type: ignore[misc]
