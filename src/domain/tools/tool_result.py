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

    def to_message_block(self) -> dict[str, object]:
        return {
            "type": "tool_result",
            "tool_use_id": self.tool_call_id,
            "content": self.output,
            "is_error": not self.success,
        }