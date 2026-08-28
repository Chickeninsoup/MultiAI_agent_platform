from __future__ import annotations

import types

import pytest

from src.execution_failure import ExecutionFailure, FailureCategory
from src.recovery_action import RecoveryAction
from src.recovery_planner import RecoveryPlanner


def test_temporary_error_maps_to_retry() -> None:
    planner = RecoveryPlanner()
    failure = ExecutionFailure(
        category=FailureCategory.TEMPORARY_ERROR, message="timeout"
    )

    assert planner.decide(failure) == RecoveryAction.RETRY


def test_plan_error_maps_to_repair_plan() -> None:
    planner = RecoveryPlanner()
    failure = ExecutionFailure(
        category=FailureCategory.PLAN_ERROR, message="invalid arguments"
    )

    assert planner.decide(failure) == RecoveryAction.REPAIR_PLAN


def test_blocked_maps_to_request_approval() -> None:
    planner = RecoveryPlanner()
    failure = ExecutionFailure(
        category=FailureCategory.BLOCKED, message="permission denied"
    )

    assert planner.decide(failure) == RecoveryAction.REQUEST_APPROVAL


def test_fatal_maps_to_abort() -> None:
    planner = RecoveryPlanner()
    failure = ExecutionFailure(
        category=FailureCategory.FATAL, message="corrupted state"
    )

    assert planner.decide(failure) == RecoveryAction.ABORT


def test_message_does_not_affect_the_decision() -> None:
    planner = RecoveryPlanner()

    decision_a = planner.decide(
        ExecutionFailure(
            category=FailureCategory.TEMPORARY_ERROR, message="timeout"
        )
    )
    decision_b = planner.decide(
        ExecutionFailure(
            category=FailureCategory.TEMPORARY_ERROR,
            message="network unavailable",
        )
    )

    assert decision_a == decision_b == RecoveryAction.RETRY


def test_step_id_does_not_affect_the_decision() -> None:
    planner = RecoveryPlanner()

    decision_a = planner.decide(
        ExecutionFailure(
            category=FailureCategory.BLOCKED,
            message="permission denied",
            step_id="step-a",
        )
    )
    decision_b = planner.decide(
        ExecutionFailure(
            category=FailureCategory.BLOCKED,
            message="permission denied",
            step_id="step-b",
        )
    )

    assert decision_a == decision_b == RecoveryAction.REQUEST_APPROVAL


def test_unrecognized_category_fails_fast() -> None:
    """Unlike FailureClassifier, an unmapped category here is a
    coverage gap, not a runtime surprise - it must raise, not
    silently default to ABORT."""

    planner = RecoveryPlanner()
    fake_failure = types.SimpleNamespace(
        category="not-a-real-category", message="x", step_id=None
    )

    with pytest.raises(ValueError):
        planner.decide(fake_failure)  # type: ignore[arg-type]
