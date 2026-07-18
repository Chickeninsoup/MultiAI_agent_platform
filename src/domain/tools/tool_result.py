from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class ToolResult:
    tool_call_id: str
    tool_name: str
    success: bool
    output: str
    error_code: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)