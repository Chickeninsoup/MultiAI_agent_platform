from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentMessage:
    sender_id: str
    receiver_id: str
    task_id: str
    content: str
    context: dict[str, Any]
