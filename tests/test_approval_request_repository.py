from __future__ import annotations

from pathlib import Path

import pytest

from src.approval_errors import InvalidApprovalIdError
from src.approval_request import ApprovalRequest, RiskLevel
from src.approval_request_repository import ApprovalRequestRepository
from src.domain.tools.tool_call import ToolCall


def _request(approval_id: str = "approval-1") -> ApprovalRequest:
    return ApprovalRequest(
        approval_id=approval_id,
        run_id="run-007",
        proposed_action=ToolCall(
            id="toolu_1", name="write_file", input={"path": "a.py"}
        ),
        reason="write_file targets a path outside the sandbox",
        risk_level=RiskLevel.MEDIUM,
        input_preview="write a.py (5 bytes)",
        created_at="2026-01-01T00:00:00Z",
    )


def test_save_and_load_roundtrip(tmp_path: Path) -> None:
    repository = ApprovalRequestRepository(tmp_path)
    request = _request()

    repository.save(request)
    loaded = repository.load("approval-1")

    assert loaded == request


def test_load_missing_request_raises(tmp_path: Path) -> None:
    repository = ApprovalRequestRepository(tmp_path)

    with pytest.raises(FileNotFoundError):
        repository.load("unknown")


def test_exists_reflects_whether_a_request_was_saved(
    tmp_path: Path,
) -> None:
    repository = ApprovalRequestRepository(tmp_path)

    assert repository.exists("approval-1") is False

    repository.save(_request())

    assert repository.exists("approval-1") is True


def test_approvals_do_not_overwrite_each_other(tmp_path: Path) -> None:
    repository = ApprovalRequestRepository(tmp_path)
    request_a = _request("approval-1")
    request_b = _request("approval-2")

    repository.save(request_a)
    repository.save(request_b)

    assert repository.load("approval-1") == request_a
    assert repository.load("approval-2") == request_b


def test_list_all_is_empty_when_nothing_was_ever_saved(
    tmp_path: Path,
) -> None:
    repository = ApprovalRequestRepository(tmp_path)

    assert repository.list_all() == []


def test_list_all_returns_every_saved_request(tmp_path: Path) -> None:
    repository = ApprovalRequestRepository(tmp_path)
    repository.save(_request("approval-2"))
    repository.save(_request("approval-1"))

    loaded = repository.list_all()

    assert {request.approval_id for request in loaded} == {
        "approval-1",
        "approval-2",
    }


def test_request_file_does_not_collide_with_resolution_file(
    tmp_path: Path,
) -> None:
    repository = ApprovalRequestRepository(tmp_path)

    file_path = repository.get_request_file("approval-1")

    assert file_path.name == "request.json"


@pytest.mark.parametrize(
    "unsafe_id",
    ["../outside", "../../task", "/absolute/path", "a/b", "..", "."],
)
def test_save_rejects_path_traversal_and_mutates_nothing(
    tmp_path: Path, unsafe_id: str
) -> None:
    repository = ApprovalRequestRepository(tmp_path)

    with pytest.raises(InvalidApprovalIdError):
        repository.save(_request(unsafe_id))

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "unsafe_id",
    ["../outside", "../../task", "/absolute/path", "a/b", "..", "."],
)
def test_load_rejects_path_traversal(
    tmp_path: Path, unsafe_id: str
) -> None:
    repository = ApprovalRequestRepository(tmp_path)

    with pytest.raises(InvalidApprovalIdError):
        repository.load(unsafe_id)


@pytest.mark.parametrize(
    "unsafe_id",
    ["../outside", "../../task", "/absolute/path", "a/b", "..", "."],
)
def test_exists_rejects_path_traversal(
    tmp_path: Path, unsafe_id: str
) -> None:
    repository = ApprovalRequestRepository(tmp_path)

    with pytest.raises(InvalidApprovalIdError):
        repository.exists(unsafe_id)
