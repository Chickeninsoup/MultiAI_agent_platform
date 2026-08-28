from __future__ import annotations

from pathlib import Path

import pytest

from src.execution_failure import ExecutionFailure, FailureCategory
from src.runtime_approval_repository import RuntimeApprovalRepository
from src.runtime_approval_request import RuntimeApprovalRequest


def _request(task_id: str = "task-a") -> RuntimeApprovalRequest:
    return RuntimeApprovalRequest(
        approval_id="approval-1",
        task_id=task_id,
        plan_id="plan-1",
        failure=ExecutionFailure(
            category=FailureCategory.BLOCKED,
            message="permission denied",
            step_id="step-c",
        ),
        created_at="2026-01-01T00:00:00Z",
    )


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    repository = RuntimeApprovalRepository(tmp_path)
    request = _request()

    repository.save(request)
    loaded = repository.load("task-a")

    assert loaded == request


def test_load_missing_approval_raises(tmp_path: Path) -> None:
    repository = RuntimeApprovalRepository(tmp_path)

    with pytest.raises(FileNotFoundError):
        repository.load("unknown")


def test_tasks_do_not_overwrite_each_other(tmp_path: Path) -> None:
    repository = RuntimeApprovalRepository(tmp_path)
    request_a = _request("task-a")
    request_b = _request("task-b")

    repository.save(request_a)
    repository.save(request_b)

    assert repository.load("task-a") == request_a
    assert repository.load("task-b") == request_b


def test_delete_removes_the_approval(tmp_path: Path) -> None:
    repository = RuntimeApprovalRepository(tmp_path)
    repository.save(_request())

    repository.delete("task-a")

    with pytest.raises(FileNotFoundError):
        repository.load("task-a")


def test_delete_is_idempotent_for_a_missing_approval(
    tmp_path: Path,
) -> None:
    repository = RuntimeApprovalRepository(tmp_path)

    repository.delete("unknown")


def test_failure_is_preserved_through_serialization(
    tmp_path: Path,
) -> None:
    repository = RuntimeApprovalRepository(tmp_path)
    request = _request()

    repository.save(request)
    loaded = repository.load("task-a")

    assert loaded.failure.category == FailureCategory.BLOCKED
    assert loaded.failure.message == "permission denied"
    assert loaded.failure.step_id == "step-c"


def test_does_not_share_a_file_with_plan_approval(
    tmp_path: Path,
) -> None:
    repository = RuntimeApprovalRepository(tmp_path)

    file_path = repository.get_runtime_approval_file("task-a")

    assert file_path.name == "runtime_approval.json"
    assert file_path.name != "approval.json"
