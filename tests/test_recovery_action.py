from __future__ import annotations

import pytest

from src.recovery_action import RecoveryAction


def test_all_four_recovery_actions_exist() -> None:
    assert RecoveryAction.RETRY
    assert RecoveryAction.REPAIR_PLAN
    assert RecoveryAction.REQUEST_APPROVAL
    assert RecoveryAction.ABORT


def test_recovery_action_values_are_correct() -> None:
    assert RecoveryAction.RETRY.value == "retry"
    assert RecoveryAction.REPAIR_PLAN.value == "repair_plan"
    assert RecoveryAction.REQUEST_APPROVAL.value == "request_approval"
    assert RecoveryAction.ABORT.value == "abort"


def test_recovery_actions_are_distinct() -> None:
    assert len(set(RecoveryAction)) == 4
    assert len({action.value for action in RecoveryAction}) == 4


def test_recovery_action_members_are_immutable() -> None:
    with pytest.raises(AttributeError):
        RecoveryAction.RETRY.value = "changed"  # type: ignore[misc]
