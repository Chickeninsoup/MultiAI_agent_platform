from __future__ import annotations

from pathlib import Path

import pytest

from src.execution_failure import ExecutionFailure, FailureCategory
from src.runtime_approval_errors import RuntimeApprovalStateError
from src.runtime_approval_repository import RuntimeApprovalRepository
from src.runtime_approval_service import RuntimeApprovalService


def _failure() -> ExecutionFailure:
    return ExecutionFailure(
        category=FailureCategory.BLOCKED,
        message="permission denied",
        step_id="step-c",
    )


def _service(tmp_path: Path) -> RuntimeApprovalService:
    return RuntimeApprovalService(RuntimeApprovalRepository(tmp_path))


def test_create_returns_a_pending_request(tmp_path: Path) -> None:
    service = _service(tmp_path)

    request = service.create("task-a", "plan-1", _failure())

    assert request.status == "pending"
    assert request.task_id == "task-a"
    assert request.plan_id == "plan-1"
    assert request.failure == _failure()


def test_create_persists_the_request(tmp_path: Path) -> None:
    repository = RuntimeApprovalRepository(tmp_path)
    service = RuntimeApprovalService(repository)

    created = service.create("task-a", "plan-1", _failure())

    assert repository.load("task-a") == created


def test_approve_transitions_pending_to_approved(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create("task-a", "plan-1", _failure())

    approved = service.approve("task-a")

    assert approved.status == "approved"


def test_reject_transitions_pending_to_rejected(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create("task-a", "plan-1", _failure())

    rejected = service.reject("task-a")

    assert rejected.status == "rejected"


def test_approve_is_persisted(tmp_path: Path) -> None:
    repository = RuntimeApprovalRepository(tmp_path)
    service = RuntimeApprovalService(repository)
    service.create("task-a", "plan-1", _failure())

    service.approve("task-a")

    assert repository.load("task-a").status == "approved"


def test_cannot_approve_an_already_approved_request(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service.create("task-a", "plan-1", _failure())
    service.approve("task-a")

    with pytest.raises(RuntimeApprovalStateError):
        service.approve("task-a")


def test_cannot_approve_a_rejected_request(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create("task-a", "plan-1", _failure())
    service.reject("task-a")

    with pytest.raises(RuntimeApprovalStateError):
        service.approve("task-a")


def test_cannot_reject_an_already_rejected_request(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)
    service.create("task-a", "plan-1", _failure())
    service.reject("task-a")

    with pytest.raises(RuntimeApprovalStateError):
        service.reject("task-a")


def test_cannot_reject_an_approved_request(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.create("task-a", "plan-1", _failure())
    service.approve("task-a")

    with pytest.raises(RuntimeApprovalStateError):
        service.reject("task-a")


def test_approve_missing_approval_raises_file_not_found(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)

    with pytest.raises(FileNotFoundError):
        service.approve("unknown")


def test_reject_missing_approval_raises_file_not_found(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)

    with pytest.raises(FileNotFoundError):
        service.reject("unknown")


def test_repeated_create_produces_distinct_approval_ids(
    tmp_path: Path,
) -> None:
    service = _service(tmp_path)

    first = service.create("task-a", "plan-1", _failure())
    service.approve("task-a")
    second = service.create("task-a", "plan-1", _failure())

    assert first.approval_id != second.approval_id
