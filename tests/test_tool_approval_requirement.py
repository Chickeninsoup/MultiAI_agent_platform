from __future__ import annotations

import pytest

from src.tool_approval_requirement import ToolApprovalRequirement


def test_both_requirements_exist() -> None:
    assert ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL
    assert ToolApprovalRequirement.REQUIRES_APPROVAL


def test_requirement_values_are_correct() -> None:
    assert (
        ToolApprovalRequirement.DOES_NOT_REQUIRE_APPROVAL.value
        == "does_not_require_approval"
    )
    assert (
        ToolApprovalRequirement.REQUIRES_APPROVAL.value
        == "requires_approval"
    )


def test_requirements_are_distinct() -> None:
    assert len(set(ToolApprovalRequirement)) == 2


def test_requirement_members_are_immutable() -> None:
    with pytest.raises(AttributeError):
        ToolApprovalRequirement.REQUIRES_APPROVAL.value = (
            "changed"  # type: ignore[misc]
        )
