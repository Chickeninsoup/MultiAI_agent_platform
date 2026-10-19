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

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_call_id": self.tool_call_id,
            "tool_name": self.tool_name,
            "success": self.success,
            "output": self.output,
            "error_code": self.error_code,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolResult":
        return cls(
            tool_call_id=data["tool_call_id"],
            tool_name=data["tool_name"],
            success=data["success"],
            output=data["output"],
            error_code=data.get("error_code"),
            metadata=data.get("metadata", {}),
        )