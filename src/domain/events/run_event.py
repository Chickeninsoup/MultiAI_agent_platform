from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RunEvent:
    event_type: str
    timestamp: str | None
    run_id: str
    data: dict[str, Any]
