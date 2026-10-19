from __future__ import annotations

import dataclasses

import pytest

from src.approval_request import RiskLevel
from src.approval_rule import ApprovalRule


def test_basic_construction() -> None:
    rule = ApprovalRule(
        tool_name="write_file",
        risk_level=RiskLevel.MEDIUM,
        reason="writes files outside the sandbox",
    )

    assert rule.tool_name == "write_file"
    assert rule.risk_level is RiskLevel.MEDIUM
    assert rule.reason == "writes files outside the sandbox"


def test_rule_is_immutable() -> None:
    rule = ApprovalRule(
        tool_name="write_file",
        risk_level=RiskLevel.MEDIUM,
        reason="writes files outside the sandbox",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        rule.reason = "changed"  # type: ignore[misc]


def test_empty_tool_name_is_rejected() -> None:
    with pytest.raises(ValueError):
        ApprovalRule(
            tool_name="",
            risk_level=RiskLevel.LOW,
            reason="some reason",
        )


def test_whitespace_only_tool_name_is_rejected() -> None:
    with pytest.raises(ValueError):
        ApprovalRule(
            tool_name="   ",
            risk_level=RiskLevel.LOW,
            reason="some reason",
        )


def test_empty_reason_is_rejected() -> None:
    with pytest.raises(ValueError):
        ApprovalRule(
            tool_name="write_file", risk_level=RiskLevel.LOW, reason=""
        )


def test_whitespace_only_reason_is_rejected() -> None:
    with pytest.raises(ValueError):
        ApprovalRule(
            tool_name="write_file",
            risk_level=RiskLevel.LOW,
            reason="   ",
        )


def test_invalid_risk_level_is_rejected() -> None:
    with pytest.raises(ValueError):
        ApprovalRule(
            tool_name="write_file",
            risk_level="high",  # type: ignore[arg-type]
            reason="some reason",
        )


@pytest.mark.parametrize(
    "risk_level", [RiskLevel.LOW, RiskLevel.MEDIUM, RiskLevel.HIGH]
)
def test_all_risk_levels_are_accepted(risk_level: RiskLevel) -> None:
    rule = ApprovalRule(
        tool_name="write_file", risk_level=risk_level, reason="reason"
    )

    assert rule.risk_level is risk_level
