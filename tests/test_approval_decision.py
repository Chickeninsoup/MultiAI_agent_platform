from __future__ import annotations

import pytest

from src.approval_decision import ApprovalDecision


def test_all_four_approval_decisions_exist() -> None:
    assert ApprovalDecision.APPROVE
    assert ApprovalDecision.REJECT
    assert ApprovalDecision.MODIFY
    assert ApprovalDecision.CANCEL


def test_approval_decision_values_are_correct() -> None:
    assert ApprovalDecision.APPROVE.value == "approve"
    assert ApprovalDecision.REJECT.value == "reject"
    assert ApprovalDecision.MODIFY.value == "modify"
    assert ApprovalDecision.CANCEL.value == "cancel"


def test_approval_decisions_are_distinct() -> None:
    assert len(set(ApprovalDecision)) == 4
    assert len({decision.value for decision in ApprovalDecision}) == 4


def test_approval_decision_members_are_immutable() -> None:
    with pytest.raises(AttributeError):
        ApprovalDecision.APPROVE.value = "changed"  # type: ignore[misc]
