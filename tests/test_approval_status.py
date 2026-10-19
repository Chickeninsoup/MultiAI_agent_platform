from __future__ import annotations

import pytest

from src.approval_status import ApprovalStatus


def test_both_approval_statuses_exist() -> None:
    assert ApprovalStatus.PENDING
    assert ApprovalStatus.RESOLVED


def test_approval_status_values_are_correct() -> None:
    assert ApprovalStatus.PENDING.value == "pending"
    assert ApprovalStatus.RESOLVED.value == "resolved"


def test_approval_statuses_are_distinct() -> None:
    assert len(set(ApprovalStatus)) == 2
    assert len({status.value for status in ApprovalStatus}) == 2


def test_approval_status_members_are_immutable() -> None:
    with pytest.raises(AttributeError):
        ApprovalStatus.PENDING.value = "changed"  # type: ignore[misc]
