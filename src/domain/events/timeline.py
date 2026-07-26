from __future__ import annotations

from dataclasses import dataclass

from src.domain.events.run_event import RunEvent


@dataclass(frozen=True)
class RunTimeline:
    run_id: str
    events: list[RunEvent]
