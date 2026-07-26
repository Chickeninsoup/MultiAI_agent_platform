from src.domain.events.run_event import RunEvent
from src.domain.events.timeline_builder import TimelineBuilder


def _event(event_type: str) -> RunEvent:
    return RunEvent(
        event_type=event_type,
        timestamp=None,
        run_id="run-001",
        data={},
    )


def test_build_wraps_events_in_a_timeline() -> None:
    events = [_event("tool_call"), _event("tool_result")]

    timeline = TimelineBuilder().build(
        run_id="run-001",
        events=events,
    )

    assert timeline.run_id == "run-001"
    assert timeline.events == events


def test_build_preserves_original_order() -> None:
    events = [
        _event("llm_response"),
        _event("tool_call"),
        _event("tool_result"),
    ]

    timeline = TimelineBuilder().build(
        run_id="run-001",
        events=events,
    )

    assert [event.event_type for event in timeline.events] == [
        "llm_response",
        "tool_call",
        "tool_result",
    ]


def test_build_does_not_sort_out_of_order_events() -> None:
    # TimelineBuilder is deliberately dumb: it doesn't reorder or
    # reinterpret anything, even if events look "out of order" -
    # EventRepository already reads events.jsonl in its natural
    # append order, so there's nothing for this layer to fix.
    events = [_event("tool_result"), _event("tool_call")]

    timeline = TimelineBuilder().build(
        run_id="run-001",
        events=events,
    )

    assert [event.event_type for event in timeline.events] == [
        "tool_result",
        "tool_call",
    ]


def test_build_supports_empty_events() -> None:
    timeline = TimelineBuilder().build(run_id="run-001", events=[])

    assert timeline.events == []
