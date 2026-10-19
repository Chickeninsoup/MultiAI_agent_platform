from __future__ import annotations

import dataclasses

import pytest

from src.approval_request import RiskLevel
from src.tool_approval_policy_result import ToolApprovalPolicyResult
from src.tool_approval_requirement import ToolApprovalRequirement


def test_does_not_require_approval_without_extra_fields() -> None:
    result = ToolApprovalPolicyResult(
        requirement=ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL,
    )

    assert (
        result.requirement
        is ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL
    )
    assert result.risk_level is None
    assert result.reason is None


def test_requires_approval_with_risk_level_and_reason() -> None:
    result = ToolApprovalPolicyResult(
        requirement=ToolApprovalRequirement.REQUIRES_APPROVAL,
        risk_level=RiskLevel.HIGH,
        reason="deletes files",
    )

    assert result.requirement is ToolApprovalRequirement.REQUIRES_APPROVAL
    assert result.risk_level is RiskLevel.HIGH
    assert result.reason == "deletes files"


def test_requires_approval_without_risk_level_is_rejected() -> None:
    with pytest.raises(ValueError):
        ToolApprovalPolicyResult(
            requirement=ToolApprovalRequirement.REQUIRES_APPROVAL,
            reason="deletes files",
        )


def test_requires_approval_without_reason_is_rejected() -> None:
    with pytest.raises(ValueError):
        ToolApprovalPolicyResult(
            requirement=ToolApprovalRequirement.REQUIRES_APPROVAL,
            risk_level=RiskLevel.HIGH,
        )


def test_requires_approval_with_empty_reason_is_rejected() -> None:
    with pytest.raises(ValueError):
        ToolApprovalPolicyResult(
            requirement=ToolApprovalRequirement.REQUIRES_APPROVAL,
            risk_level=RiskLevel.HIGH,
            reason="   ",
        )


def test_does_not_require_approval_with_risk_level_is_rejected() -> None:
    with pytest.raises(ValueError):
        ToolApprovalPolicyResult(
            requirement=(
                ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL
            ),
            risk_level=RiskLevel.LOW,
        )


def test_does_not_require_approval_with_reason_is_rejected() -> None:
    with pytest.raises(ValueError):
        ToolApprovalPolicyResult(
            requirement=(
                ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL
            ),
            reason="some reason",
        )


def test_assigning_requirement_raises_frozen_instance_error() -> None:
    result = ToolApprovalPolicyResult(
        requirement=ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL,
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.requirement = (  # type: ignore[misc]
            ToolApprovalRequirement.REQUIRES_APPROVAL
        )


def test_assigning_risk_level_raises_frozen_instance_error() -> None:
    result = ToolApprovalPolicyResult(
        requirement=ToolApprovalRequirement.REQUIRES_APPROVAL,
        risk_level=RiskLevel.HIGH,
        reason="deletes files",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.risk_level = RiskLevel.LOW  # type: ignore[misc]


def test_assigning_reason_raises_frozen_instance_error() -> None:
    result = ToolApprovalPolicyResult(
        requirement=ToolApprovalRequirement.REQUIRES_APPROVAL,
        risk_level=RiskLevel.HIGH,
        reason="deletes files",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.reason = "changed"  # type: ignore[misc]
