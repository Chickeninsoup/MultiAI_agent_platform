from __future__ import annotations

import dataclasses

import pytest

from src.execution_failure import ExecutionFailure, FailureCategory
from src.runtime_approval_request import RuntimeApprovalRequest


def _failure() -> ExecutionFailure:
    return ExecutionFailure(
        category=FailureCategory.BLOCKED,
        message="permission denied",
        step_id="step-3",
    )


def test_basic_construction() -> None:
    failure = _failure()
    request = RuntimeApprovalRequest(
        approval_id="approval-1",
        task_id="task-1",
        plan_id="plan-1",
        failure=failure,
    )

    assert request.approval_id == "approval-1"
    assert request.task_id == "task-1"
    assert request.plan_id == "plan-1"
    assert request.failure is failure


def test_status_defaults_to_pending() -> None:
    request = RuntimeApprovalRequest(
        approval_id="approval-1",
        task_id="task-1",
        plan_id="plan-1",
        failure=_failure(),
    )

    assert request.status == "pending"


def test_request_is_immutable() -> None:
    request = RuntimeApprovalRequest(
        approval_id="approval-1",
        task_id="task-1",
        plan_id="plan-1",
        failure=_failure(),
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        request.status = "approved"


def test_failure_is_preserved_in_full() -> None:
    failure = _failure()
    request = RuntimeApprovalRequest(
        approval_id="approval-1",
        task_id="task-1",
        plan_id="plan-1",
        failure=failure,
    )

    assert request.failure.category == FailureCategory.BLOCKED
    assert request.failure.message == "permission denied"
    assert request.failure.step_id == "step-3"


def test_status_transitions_via_replace_not_mutation() -> None:
    """5E-5C-8D-2 is model only - RuntimeApprovalRequest does not
    enforce transitions itself, but a new status is produced via
    dataclasses.replace, not by mutating the pending request."""

    pending = RuntimeApprovalRequest(
        approval_id="approval-1",
        task_id="task-1",
        plan_id="plan-1",
        failure=_failure(),
    )

    approved = dataclasses.replace(pending, status="approved")

    assert pending.status == "pending"
    assert approved.status == "approved"
    assert approved.approval_id == pending.approval_id


def test_to_dict_and_from_dict_roundtrip() -> None:
    request = RuntimeApprovalRequest(
        approval_id="approval-1",
        task_id="task-1",
        plan_id="plan-1",
        failure=_failure(),
        created_at="2026-01-01T00:00:00Z",
    )

    assert RuntimeApprovalRequest.from_dict(request.to_dict()) == request
