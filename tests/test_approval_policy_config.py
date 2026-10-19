from __future__ import annotations

from pathlib import Path

import pytest

from src.approval_policy_config import (
    ApprovalPolicyConfigError,
    load_approval_rules,
    parse_approval_rules,
)
from src.approval_request import RiskLevel

KNOWN_TOOLS = frozenset({"write_file", "read_file"})


def test_empty_rules_list_is_valid_and_empty() -> None:
    rules = parse_approval_rules(
        {"rules": []}, known_tool_names=KNOWN_TOOLS
    )

    assert rules == []


def test_valid_single_rule_parses() -> None:
    rules = parse_approval_rules(
        {
            "rules": [
                {
                    "tool_name": "write_file",
                    "risk_level": "medium",
                    "reason": "writes files inside the repository",
                }
            ]
        },
        known_tool_names=KNOWN_TOOLS,
    )

    assert len(rules) == 1
    assert rules[0].tool_name == "write_file"
    assert rules[0].risk_level is RiskLevel.MEDIUM
    assert rules[0].reason == "writes files inside the repository"


def test_multiple_distinct_rules_parse() -> None:
    rules = parse_approval_rules(
        {
            "rules": [
                {
                    "tool_name": "write_file",
                    "risk_level": "medium",
                    "reason": "writes files",
                },
                {
                    "tool_name": "read_file",
                    "risk_level": "low",
                    "reason": "reads files",
                },
            ]
        },
        known_tool_names=KNOWN_TOOLS,
    )

    assert {rule.tool_name for rule in rules} == {
        "write_file",
        "read_file",
    }


def test_root_must_be_object() -> None:
    with pytest.raises(ApprovalPolicyConfigError):
        parse_approval_rules([], known_tool_names=KNOWN_TOOLS)


def test_unexpected_root_key_rejected() -> None:
    with pytest.raises(ApprovalPolicyConfigError):
        parse_approval_rules(
            {"rules": [], "extra": 1}, known_tool_names=KNOWN_TOOLS
        )


def test_rules_must_be_a_list() -> None:
    with pytest.raises(ApprovalPolicyConfigError):
        parse_approval_rules({"rules": {}}, known_tool_names=KNOWN_TOOLS)


def test_duplicate_tool_name_rejected() -> None:
    with pytest.raises(ApprovalPolicyConfigError):
        parse_approval_rules(
            {
                "rules": [
                    {
                        "tool_name": "write_file",
                        "risk_level": "low",
                        "reason": "a",
                    },
                    {
                        "tool_name": "write_file",
                        "risk_level": "high",
                        "reason": "b",
                    },
                ]
            },
            known_tool_names=KNOWN_TOOLS,
        )


def test_invalid_risk_level_rejected() -> None:
    with pytest.raises(ApprovalPolicyConfigError):
        parse_approval_rules(
            {
                "rules": [
                    {
                        "tool_name": "write_file",
                        "risk_level": "extreme",
                        "reason": "a",
                    }
                ]
            },
            known_tool_names=KNOWN_TOOLS,
        )


def test_empty_reason_rejected() -> None:
    with pytest.raises(ApprovalPolicyConfigError):
        parse_approval_rules(
            {
                "rules": [
                    {
                        "tool_name": "write_file",
                        "risk_level": "low",
                        "reason": "   ",
                    }
                ]
            },
            known_tool_names=KNOWN_TOOLS,
        )


def test_empty_tool_name_rejected() -> None:
    with pytest.raises(ApprovalPolicyConfigError):
        parse_approval_rules(
            {
                "rules": [
                    {"tool_name": "", "risk_level": "low", "reason": "a"}
                ]
            },
            known_tool_names=KNOWN_TOOLS,
        )


def test_unknown_tool_name_rejected() -> None:
    with pytest.raises(ApprovalPolicyConfigError):
        parse_approval_rules(
            {
                "rules": [
                    {
                        "tool_name": "delete_everything",
                        "risk_level": "high",
                        "reason": "a",
                    }
                ]
            },
            known_tool_names=KNOWN_TOOLS,
        )


def test_unexpected_rule_field_rejected() -> None:
    with pytest.raises(ApprovalPolicyConfigError):
        parse_approval_rules(
            {
                "rules": [
                    {
                        "tool_name": "write_file",
                        "risk_level": "low",
                        "reason": "a",
                        "extra_field": True,
                    }
                ]
            },
            known_tool_names=KNOWN_TOOLS,
        )


def test_non_object_rule_rejected() -> None:
    with pytest.raises(ApprovalPolicyConfigError):
        parse_approval_rules(
            {"rules": ["not an object"]}, known_tool_names=KNOWN_TOOLS
        )


def test_single_bad_rule_fails_whole_load_not_partial() -> None:
    with pytest.raises(ApprovalPolicyConfigError):
        parse_approval_rules(
            {
                "rules": [
                    {
                        "tool_name": "write_file",
                        "risk_level": "low",
                        "reason": "a",
                    },
                    {
                        "tool_name": "read_file",
                        "risk_level": "not-a-level",
                        "reason": "b",
                    },
                ]
            },
            known_tool_names=KNOWN_TOOLS,
        )


# --- file loading -----------------------------------------------------


def test_load_missing_file_fails(tmp_path: Path) -> None:
    with pytest.raises(ApprovalPolicyConfigError):
        load_approval_rules(
            tmp_path / "missing.json", known_tool_names=KNOWN_TOOLS
        )


def test_load_invalid_json_fails(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text("{not valid json", encoding="utf-8")

    with pytest.raises(ApprovalPolicyConfigError):
        load_approval_rules(path, known_tool_names=KNOWN_TOOLS)


def test_load_valid_file_succeeds(tmp_path: Path) -> None:
    path = tmp_path / "policy.json"
    path.write_text(
        '{"rules": [{"tool_name": "write_file", "risk_level": '
        '"medium", "reason": "writes files"}]}',
        encoding="utf-8",
    )

    rules = load_approval_rules(path, known_tool_names=KNOWN_TOOLS)

    assert len(rules) == 1
    assert rules[0].tool_name == "write_file"
