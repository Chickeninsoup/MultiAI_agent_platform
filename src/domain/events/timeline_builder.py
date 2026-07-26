from __future__ import annotations

from src.domain.events.run_event import RunEvent
from src.domain.events.timeline import RunTimeline


class TimelineBuilder:
    def build(
        self,
        run_id: str,
        events: list[RunEvent],
    ) -> RunTimeline:
        return RunTimeline(
            run_id=run_id,
            events=events,
        )
