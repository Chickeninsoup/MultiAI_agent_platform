from enum import Enum
from typing import Protocol


class ToolRetentionClass(str, Enum):
    """How willing a compactor should be to drop this tool's exchange.

    Three states, not a bool - EVICTABLE/PROTECTED alone can't
    represent "no opinion," and defaulting an unrecognized tool to
    either extreme is wrong in a different way (see
    RuleBasedToolRetentionPolicy's NORMAL default).
    """

    PROTECTED = "protected"
    NORMAL = "normal"
    EVICTABLE = "evictable"


class ToolRetentionPolicy(Protocol):
    """Something that can classify a tool by retention priority.

    Structural, matching this codebase's HistorySizeEstimator/
    ContextSelector convention - rule-based today, could be
    LLM-judged or statistics-based later without callers changing.
    """

    def classify(self, tool_name: str | None) -> ToolRetentionClass:
        ...


_PROTECTED_TOOLS = {
    "apply_patch",
    "write_file",
    "create_file",
    "delete_file",
    "git_commit",
}

_EVICTABLE_TOOLS = {
    "read_file",
    "list_files",
    "search",
}


class RuleBasedToolRetentionPolicy:
    """Default ToolRetentionPolicy: a fixed protected/evictable set.

    Unknown tools (including None, for non-tool-exchange groups)
    classify as NORMAL, not EVICTABLE - a new tool this policy has
    never heard of (e.g. a future deploy_service) must not be silently
    treated as safe to drop just because it's unrecognized. Safe
    default is "keep," not "discard."
    """

    def classify(self, tool_name: str | None) -> ToolRetentionClass:
        if tool_name in _PROTECTED_TOOLS:
            return ToolRetentionClass.PROTECTED

        if tool_name in _EVICTABLE_TOOLS:
            return ToolRetentionClass.EVICTABLE

        return ToolRetentionClass.NORMAL
