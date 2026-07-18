from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class FilesystemPolicy:
    readable_paths: list[str]
    writable_paths: list[str]


@dataclass(frozen=True)
class NetworkPolicy:
    internet_access: bool
    allowed_domains: list[str]


@dataclass(frozen=True)
class ToolPolicy:
    allowed_tools: list[str]
    denied_tools: list[str]
    network_policy: NetworkPolicy
    filesystem_policy: FilesystemPolicy
    requires_human_approval: list[str]


class ToolPolicyService(Protocol):
    """Provider-independent interface for checking tool policy."""

    def is_tool_allowed(self, tool_name: str) -> bool:
        ...

    def requires_approval(self, tool_name: str) -> bool:
        ...
