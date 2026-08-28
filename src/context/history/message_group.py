from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class MessageGroupKind(str, Enum):
    """Coarse categories MessageGroupBuilder assigns - three only.

    ERROR_RECOVERY/STATE_CHANGE/VERIFICATION etc. are real future
    categories, but adding them now would mean guessing at
    distinctions nothing consumes yet. Grow this once a compaction
    policy actually needs to treat those differently.
    """

    INITIAL_TASK = "initial_task"
    NORMAL = "normal"
    TOOL_EXCHANGE = "tool_exchange"


@dataclass(frozen=True)
class MessageGroup:
    """A run of one or more LLMMessage indices treated as one unit.

    Holds indices, not the LLMMessages themselves - same reasoning as
    CompactionPlan.retained_indices: no data copy, stays aligned with
    whatever messages list it was built from, and a decision made
    from groups stays auditable back to the original history. Frozen
    because a group is an observation about existing history, not
    something later code should be able to quietly edit.

    tool_name is a plain str | None field, not a generic metadata
    dict - a dict invites stringly-typed keys ("tool", "name",
    "tool_name") drifting out of sync across call sites. Only
    TOOL_EXCHANGE groups ever have one; INITIAL_TASK/NORMAL groups
    leave it None. Add the next typed field the same way when a real
    need shows up, rather than opening a dict now for one that
    doesn't exist yet.
    """

    indices: tuple[int, ...]
    kind: MessageGroupKind
    tool_name: str | None = None
