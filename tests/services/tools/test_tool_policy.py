import json
from pathlib import Path

import pytest

from src.services.tools.tool_policy import (
    ToolPolicyError,
    load_tool_policy,
    parse_tool_policy,
)


def test_loads_valid_policy(tmp_path: Path) -> None:
    policy_path = tmp_path / "tool-policy.json"
    policy_path.write_text(
        json.dumps(
            {
                "default": "deny",
                "tools": {
                    "read_file": {
                        "enabled": True,
                        "max_output_chars": 5000,
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    policy = load_tool_policy(policy_path)

    assert policy.is_enabled("read_file") is True
    assert policy.is_enabled("unknown_tool") is False
    assert (
        policy.get_max_output_chars(
            "read_file",
            fallback=1000,
        )
        == 5000
    )


def test_default_allow_enables_unknown_tool() -> None:
    policy = parse_tool_policy(
        {
            "default": "allow",
            "tools": {},
        }
    )

    assert policy.is_enabled("unknown_tool") is True


def test_explicit_disable_overrides_default_allow() -> None:
    policy = parse_tool_policy(
        {
            "default": "allow",
            "tools": {
                "read_file": {
                    "enabled": False,
                }
            },
        }
    )

    assert policy.is_enabled("read_file") is False


def test_rejects_invalid_default() -> None:
    with pytest.raises(ToolPolicyError):
        parse_tool_policy(
            {
                "default": "sometimes",
                "tools": {},
            }
        )


def test_rejects_non_boolean_enabled() -> None:
    with pytest.raises(ToolPolicyError):
        parse_tool_policy(
            {
                "default": "deny",
                "tools": {
                    "read_file": {
                        "enabled": "yes",
                    }
                },
            }
        )


def test_rejects_invalid_output_limit() -> None:
    with pytest.raises(ToolPolicyError):
        parse_tool_policy(
            {
                "default": "deny",
                "tools": {
                    "read_file": {
                        "enabled": True,
                        "max_output_chars": 0,
                    }
                },
            }
        )


def test_loads_max_write_bytes() -> None:
    policy = parse_tool_policy(
        {
            "default": "deny",
            "tools": {
                "write_file": {
                    "enabled": True,
                    "max_write_bytes": 2000,
                }
            },
        }
    )

    assert (
        policy.get_max_write_bytes(
            "write_file",
            fallback=1000,
        )
        == 2000
    )


def test_get_max_write_bytes_falls_back_when_unset() -> None:
    policy = parse_tool_policy(
        {
            "default": "deny",
            "tools": {
                "write_file": {
                    "enabled": True,
                }
            },
        }
    )

    assert (
        policy.get_max_write_bytes(
            "write_file",
            fallback=1000,
        )
        == 1000
    )


def test_rejects_invalid_write_size_limit() -> None:
    with pytest.raises(ToolPolicyError):
        parse_tool_policy(
            {
                "default": "deny",
                "tools": {
                    "write_file": {
                        "enabled": True,
                        "max_write_bytes": 0,
                    }
                },
            }
        )


def test_rejects_unknown_policy_field() -> None:
    with pytest.raises(ToolPolicyError):
        parse_tool_policy(
            {
                "default": "deny",
                "tools": {},
                "unexpected": True,
            }
        )
