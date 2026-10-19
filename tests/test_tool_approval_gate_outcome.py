from __future__ import annotations

import pytest

from src.tool_approval_gate_outcome import ToolApprovalGateOutcome


def test_both_outcomes_exist() -> None:
    assert ToolApprovalGateOutcome.PROCEED
    assert ToolApprovalGateOutcome.WAITING_FOR_APPROVAL


def test_outcome_values_are_correct() -> None:
    assert ToolApprovalGateOutcome.PROCEED.value == "proceed"
    assert (
        ToolApprovalGateOutcome.WAITING_FOR_APPROVAL.value
        == "waiting_for_approval"
    )


def test_outcomes_are_distinct() -> None:
    assert len(set(ToolApprovalGateOutcome)) == 2


def test_outcome_members_are_immutable() -> None:
    with pytest.raises(AttributeError):
        ToolApprovalGateOutcome.PROCEED.value = (
            "changed"  # type: ignore[misc]
        )
