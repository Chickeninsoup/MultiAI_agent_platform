from __future__ import annotations

import copy

import pytest

from src.approval_request import RiskLevel
from src.approval_rule import ApprovalRule
from src.domain.tools.tool_call import ToolCall
from src.rule_based_tool_approval_policy import (
    RuleBasedToolApprovalPolicy,
)
from src.tool_approval_requirement import ToolApprovalRequirement


def _tool_call(name: str, id_: str = "toolu_1") -> ToolCall:
    return ToolCall(id=id_, name=name, input={"path": "a.py"})


def test_configured_tool_requires_approval() -> None:
    policy = RuleBasedToolApprovalPolicy(
        [
            ApprovalRule(
                tool_name="write_file",
                risk_level=RiskLevel.MEDIUM,
                reason="writes files outside the sandbox",
            )
        ]
    )

    result = policy.evaluate(_tool_call("write_file"))

    assert result.requirement is ToolApprovalRequirement.REQUIRES_APPROVAL


def test_result_carries_the_configured_risk_level_and_reason() -> None:
    policy = RuleBasedToolApprovalPolicy(
        [
            ApprovalRule(
                tool_name="write_file",
                risk_level=RiskLevel.HIGH,
                reason="writes files outside the sandbox",
            )
        ]
    )

    result = policy.evaluate(_tool_call("write_file"))

    assert result.risk_level is RiskLevel.HIGH
    assert result.reason == "writes files outside the sandbox"


def test_unconfigured_tool_does_not_require_approval() -> None:
    policy = RuleBasedToolApprovalPolicy(
        [
            ApprovalRule(
                tool_name="write_file",
                risk_level=RiskLevel.MEDIUM,
                reason="writes files outside the sandbox",
            )
        ]
    )

    result = policy.evaluate(_tool_call("read_file"))

    assert (
        result.requirement
        is ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL
    )
    assert result.risk_level is None
    assert result.reason is None


def test_policy_with_no_rules_never_requires_approval() -> None:
    policy = RuleBasedToolApprovalPolicy([])

    result = policy.evaluate(_tool_call("write_file"))

    assert (
        result.requirement
        is ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL
    )


def test_duplicate_tool_rules_are_rejected() -> None:
    with pytest.raises(ValueError):
        RuleBasedToolApprovalPolicy(
            [
                ApprovalRule(
                    tool_name="write_file",
                    risk_level=RiskLevel.MEDIUM,
                    reason="reason one",
                ),
                ApprovalRule(
                    tool_name="write_file",
                    risk_level=RiskLevel.HIGH,
                    reason="reason two",
                ),
            ]
        )


def test_tool_name_matching_is_exact_and_case_sensitive() -> None:
    policy = RuleBasedToolApprovalPolicy(
        [
            ApprovalRule(
                tool_name="write_file",
                risk_level=RiskLevel.MEDIUM,
                reason="writes files outside the sandbox",
            )
        ]
    )

    assert (
        policy.evaluate(_tool_call("Write_File")).requirement
        is ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL
    )
    assert (
        policy.evaluate(_tool_call("WRITE_FILE")).requirement
        is ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL
    )
    assert (
        policy.evaluate(_tool_call("write_file2")).requirement
        is ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL
    )


def test_multiple_tools_are_configured_independently() -> None:
    policy = RuleBasedToolApprovalPolicy(
        [
            ApprovalRule(
                tool_name="write_file",
                risk_level=RiskLevel.MEDIUM,
                reason="writes files outside the sandbox",
            ),
            ApprovalRule(
                tool_name="run_test",
                risk_level=RiskLevel.LOW,
                reason="executes a whitelisted test command",
            ),
        ]
    )

    write_result = policy.evaluate(_tool_call("write_file"))
    test_result = policy.evaluate(_tool_call("run_test"))
    read_result = policy.evaluate(_tool_call("read_file"))

    assert write_result.requirement is (
        ToolApprovalRequirement.REQUIRES_APPROVAL
    )
    assert write_result.risk_level is RiskLevel.MEDIUM

    assert test_result.requirement is (
        ToolApprovalRequirement.REQUIRES_APPROVAL
    )
    assert test_result.risk_level is RiskLevel.LOW

    assert read_result.requirement is (
        ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL
    )


def test_evaluation_is_deterministic_across_repeated_calls() -> None:
    policy = RuleBasedToolApprovalPolicy(
        [
            ApprovalRule(
                tool_name="write_file",
                risk_level=RiskLevel.MEDIUM,
                reason="writes files outside the sandbox",
            )
        ]
    )
    tool_call = _tool_call("write_file")

    first = policy.evaluate(tool_call)
    second = policy.evaluate(tool_call)

    assert first.requirement == second.requirement
    assert first.risk_level == second.risk_level
    assert first.reason == second.reason


def test_evaluate_does_not_mutate_the_tool_call() -> None:
    policy = RuleBasedToolApprovalPolicy(
        [
            ApprovalRule(
                tool_name="write_file",
                risk_level=RiskLevel.MEDIUM,
                reason="writes files outside the sandbox",
            )
        ]
    )
    tool_call = _tool_call("write_file")
    original = copy.deepcopy(tool_call)

    policy.evaluate(tool_call)

    assert tool_call == original


def test_mutating_the_original_rules_list_does_not_affect_the_policy() -> (
    None
):
    rules = [
        ApprovalRule(
            tool_name="write_file",
            risk_level=RiskLevel.MEDIUM,
            reason="writes files outside the sandbox",
        )
    ]
    policy = RuleBasedToolApprovalPolicy(rules)

    rules.append(
        ApprovalRule(
            tool_name="run_test",
            risk_level=RiskLevel.LOW,
            reason="added after construction",
        )
    )
    rules.clear()

    result = policy.evaluate(_tool_call("write_file"))

    assert result.requirement is ToolApprovalRequirement.REQUIRES_APPROVAL
    assert result.risk_level is RiskLevel.MEDIUM


def test_result_never_carries_the_tool_calls_input() -> None:
    policy = RuleBasedToolApprovalPolicy(
        [
            ApprovalRule(
                tool_name="write_file",
                risk_level=RiskLevel.MEDIUM,
                reason="writes files outside the sandbox",
            )
        ]
    )

    result = policy.evaluate(
        _tool_call("write_file")
    )

    assert not hasattr(result, "input")
    assert not hasattr(result, "tool_call")
    assert not hasattr(result, "proposed_action")
