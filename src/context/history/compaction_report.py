from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class CompactionReport:
    """A serializable explanation of a compaction decision, for debugging.

    retained_groups/removed_groups are plain dicts, not
    list[MessageGroup] - this is built for logging (events.jsonl) and
    human inspection, not for driving further runtime logic, so it
    should serialize straight to JSON without a custom encoder for
    MessageGroupKind/MessageGroup. Each entry looks like:
    {"group": 3, "kind": "tool_exchange", "tool": "apply_patch",
    "reason": "protected_tool"}.
    """

    retained_count: int
    removed_count: int
    original_tokens: int
    retained_tokens: int
    retained_groups: list[dict[str, Any]] = field(default_factory=list)
    removed_groups: list[dict[str, Any]] = field(default_factory=list)
