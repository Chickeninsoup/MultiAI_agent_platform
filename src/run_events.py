from __future__ import annotations

import json
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Any, Protocol


RunEvent = dict[str, Any]


class RunEventSink(Protocol):
    """Receives structured events produced during one run."""

    def emit(self, event: RunEvent) -> None:
        ...


class NullRunEventSink:
    """Drops all events."""

    def emit(self, event: RunEvent) -> None:
        del event


class InMemoryRunEventSink:
    """Stores events in memory for tests."""

    def __init__(self) -> None:
        self.events: list[RunEvent] = []

    def emit(self, event: RunEvent) -> None:
        self.events.append(event)


class JsonlRunEventSink:
    """Appends each event to a JSONL file, one line per event, flushing
    immediately.

    Deliberately simple for the current project scale: opens and closes
    the file on every emit rather than holding a long-lived handle, so a
    mid-run crash never depends on a context manager's final close. If
    tool-call volume grows enough to make per-emit open/close costly,
    switch to a held-open handle then.
    """

    def __init__(
        self,
        events_path: Path,
        *,
        truncate_existing: bool = False,
    ) -> None:
        self._events_path = events_path
        self._events_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        if truncate_existing:
            self._events_path.write_text(
                "",
                encoding="utf-8",
            )

    def emit(self, event: RunEvent) -> None:
        normalized_event = _normalize_event(event)

        with self._events_path.open(
            "a",
            encoding="utf-8",
        ) as events_file:
            events_file.write(
                json.dumps(
                    normalized_event,
                    ensure_ascii=False,
                )
            )
            events_file.write("\n")
            events_file.flush()


def _normalize_event(event: Any) -> dict[str, Any]:
    if is_dataclass(event):
        raw_event = asdict(event)
    elif isinstance(event, dict):
        raw_event = dict(event)
    else:
        raise TypeError(
            "Run event must be a dictionary or dataclass."
        )

    return raw_event
