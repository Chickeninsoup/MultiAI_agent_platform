from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class ToolPolicyError(Exception):
    """Raised when a tool policy file is invalid."""

    error_code = "INVALID_TOOL_POLICY"


@dataclass(frozen=True)
class ToolPolicyEntry:
    enabled: bool
    max_output_chars: int | None = None
    max_write_bytes: int | None = None


@dataclass(frozen=True)
class ToolPolicy:
    default: str
    tools: dict[str, ToolPolicyEntry]

    def is_enabled(self, tool_name: str) -> bool:
        entry = self.tools.get(tool_name)

        if entry is not None:
            return entry.enabled

        return self.default == "allow"

    def get_max_output_chars(
        self,
        tool_name: str,
        fallback: int,
    ) -> int:
        entry = self.tools.get(tool_name)

        if (
            entry is not None
            and entry.max_output_chars is not None
        ):
            return entry.max_output_chars

        return fallback

    def get_max_write_bytes(
        self,
        tool_name: str,
        fallback: int,
    ) -> int:
        entry = self.tools.get(tool_name)

        if (
            entry is not None
            and entry.max_write_bytes is not None
        ):
            return entry.max_write_bytes

        return fallback


def load_tool_policy(policy_path: Path) -> ToolPolicy:
    try:
        raw_text = policy_path.read_text(encoding="utf-8")
    except FileNotFoundError as error:
        raise ToolPolicyError(
            f"Tool policy file does not exist: {policy_path}"
        ) from error

    try:
        raw_policy = json.loads(raw_text)
    except json.JSONDecodeError as error:
        raise ToolPolicyError(
            f"Tool policy is not valid JSON: {policy_path}"
        ) from error

    return parse_tool_policy(raw_policy)


def parse_tool_policy(raw_policy: Any) -> ToolPolicy:
    if not isinstance(raw_policy, dict):
        raise ToolPolicyError(
            "Tool policy root must be an object."
        )

    allowed_root_keys = {"default", "tools"}
    unexpected_root_keys = set(raw_policy) - allowed_root_keys

    if unexpected_root_keys:
        unexpected = ", ".join(
            sorted(unexpected_root_keys)
        )
        raise ToolPolicyError(
            f"Unexpected policy fields: {unexpected}"
        )

    default = raw_policy.get("default")

    if default not in {"allow", "deny"}:
        raise ToolPolicyError(
            "'default' must be either 'allow' or 'deny'."
        )

    raw_tools = raw_policy.get("tools")

    if not isinstance(raw_tools, dict):
        raise ToolPolicyError(
            "'tools' must be an object."
        )

    tools: dict[str, ToolPolicyEntry] = {}

    for tool_name, raw_entry in raw_tools.items():
        if not isinstance(tool_name, str) or not tool_name:
            raise ToolPolicyError(
                "Tool names must be non-empty strings."
            )

        tools[tool_name] = _parse_tool_entry(
            tool_name,
            raw_entry,
        )

    return ToolPolicy(
        default=default,
        tools=tools,
    )


def _parse_tool_entry(
    tool_name: str,
    raw_entry: Any,
) -> ToolPolicyEntry:
    if not isinstance(raw_entry, dict):
        raise ToolPolicyError(
            f"Policy for '{tool_name}' must be an object."
        )

    allowed_keys = {
        "enabled",
        "max_output_chars",
        "max_write_bytes",
    }
    unexpected_keys = set(raw_entry) - allowed_keys

    if unexpected_keys:
        unexpected = ", ".join(sorted(unexpected_keys))
        raise ToolPolicyError(
            f"Unexpected fields for '{tool_name}': "
            f"{unexpected}"
        )

    enabled = raw_entry.get("enabled")

    if not isinstance(enabled, bool):
        raise ToolPolicyError(
            f"'enabled' for '{tool_name}' must be boolean."
        )

    max_output_chars = raw_entry.get("max_output_chars")

    if max_output_chars is not None:
        if (
            not isinstance(max_output_chars, int)
            or isinstance(max_output_chars, bool)
            or max_output_chars < 1
        ):
            raise ToolPolicyError(
                f"'max_output_chars' for '{tool_name}' "
                "must be a positive integer."
            )

    max_write_bytes = raw_entry.get("max_write_bytes")

    if max_write_bytes is not None:
        if (
            not isinstance(max_write_bytes, int)
            or isinstance(max_write_bytes, bool)
            or max_write_bytes < 1
        ):
            raise ToolPolicyError(
                f"'max_write_bytes' for '{tool_name}' "
                "must be a positive integer."
            )

    return ToolPolicyEntry(
        enabled=enabled,
        max_output_chars=max_output_chars,
        max_write_bytes=max_write_bytes,
    )