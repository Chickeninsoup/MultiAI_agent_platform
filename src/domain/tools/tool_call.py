from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolCall:
    id: str
    name: str
    input: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {"id": self.id, "name": self.name, "input": self.input}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ToolCall":
        return cls(
            id=data["id"], name=data["name"], input=data["input"]
        )