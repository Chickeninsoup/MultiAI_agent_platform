from __future__ import annotations

from pathlib import Path

import pytest

from src.approval_decision import ApprovalDecision
from src.approval_errors import InvalidApprovalIdError
from src.approval_resolution import ApprovalResolution
from src.approval_resolution_repository import (
    ApprovalResolutionRepository,
)


def _resolution(approval_id: str = "approval-1") -> ApprovalResolution:
    return ApprovalResolution(
        approval_id=approval_id,
        decision=ApprovalDecision.APPROVE,
        resolved_at="2026-01-01T00:00:00Z",
    )


def test_save_and_get_roundtrip(tmp_path: Path) -> None:
    repository = ApprovalResolutionRepository(tmp_path)
    resolution = _resolution()

    repository.save(resolution)
    loaded = repository.get("approval-1")

    assert loaded == resolution


def test_get_returns_none_when_unresolved(tmp_path: Path) -> None:
    repository = ApprovalResolutionRepository(tmp_path)

    assert repository.get("unknown") is None


def test_approvals_do_not_overwrite_each_other(tmp_path: Path) -> None:
    repository = ApprovalResolutionRepository(tmp_path)
    resolution_a = _resolution("approval-1")
    resolution_b = _resolution("approval-2")

    repository.save(resolution_a)
    repository.save(resolution_b)

    assert repository.get("approval-1") == resolution_a
    assert repository.get("approval-2") == resolution_b


def test_modify_resolution_roundtrips_its_modified_input(
    tmp_path: Path,
) -> None:
    repository = ApprovalResolutionRepository(tmp_path)
    resolution = ApprovalResolution(
        approval_id="approval-1",
        decision=ApprovalDecision.MODIFY,
        modified_input={"path": "sandbox/safe.py"},
    )

    repository.save(resolution)
    loaded = repository.get("approval-1")

    assert loaded == resolution
    assert loaded.modified_input == {"path": "sandbox/safe.py"}


def test_resolution_file_does_not_collide_with_request_file(
    tmp_path: Path,
) -> None:
    repository = ApprovalResolutionRepository(tmp_path)

    file_path = repository.get_resolution_file("approval-1")

    assert file_path.name == "resolution.json"


@pytest.mark.parametrize(
    "unsafe_id",
    ["../outside", "../../task", "/absolute/path", "a/b", "..", "."],
)
def test_save_rejects_path_traversal_and_mutates_nothing(
    tmp_path: Path, unsafe_id: str
) -> None:
    repository = ApprovalResolutionRepository(tmp_path)

    with pytest.raises(InvalidApprovalIdError):
        repository.save(_resolution(unsafe_id))

    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "unsafe_id",
    ["../outside", "../../task", "/absolute/path", "a/b", "..", "."],
)
def test_get_rejects_path_traversal_rather_than_returning_none(
    tmp_path: Path, unsafe_id: str
) -> None:
    repository = ApprovalResolutionRepository(tmp_path)

    with pytest.raises(InvalidApprovalIdError):
        repository.get(unsafe_id)
