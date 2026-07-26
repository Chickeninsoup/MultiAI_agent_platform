from __future__ import annotations

import json
from pathlib import Path

from src.domain.events.run_event import RunEvent


class EventRepository:
    def load_events(
        self,
        events_path: Path,
        run_id: str,
    ) -> list[RunEvent]:
        events: list[RunEvent] = []

        if not events_path.exists():
            return events

        with events_path.open(
            "r",
            encoding="utf-8",
        ) as file:
            for line in file:
                if not line.strip():
                    continue

                payload = json.loads(line)

                events.append(
                    RunEvent(
                        event_type=payload.get(
                            "type",
                            "unknown",
                        ),
                        timestamp=payload.get("timestamp"),
                        run_id=run_id,
                        data=payload,
                    )
                )

        return events
