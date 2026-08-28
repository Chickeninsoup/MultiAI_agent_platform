from __future__ import annotations

from pathlib import Path

from src.planning.approval_record import ApprovalRecord
from src.planning.approval_repository import ApprovalRepository


def test_save_and_get(tmp_path: Path) -> None:
    repo = ApprovalRepository(tmp_path)
    approval = ApprovalRecord(
        task_id="task-1",
        created_at="2026-08-13T00:00:00Z",
        status="approved",
    )

    repo.save(approval)
    loaded = repo.get("task-1")

    assert loaded == approval


def test_missing_approval(tmp_path: Path) -> None:
    repo = ApprovalRepository(tmp_path)

    assert repo.get("missing") is None


def test_pending_round_trips(tmp_path: Path) -> None:
    repo = ApprovalRepository(tmp_path)
    approval = ApprovalRecord(task_id="task-1")

    repo.save(approval)

    assert repo.get("task-1").status == "pending"


def test_rejected_round_trips(tmp_path: Path) -> None:
    repo = ApprovalRepository(tmp_path)
    approval = ApprovalRecord(task_id="task-1", status="rejected")

    repo.save(approval)

    assert repo.get("task-1").status == "rejected"


def test_list_pending(tmp_path: Path) -> None:
    repo = ApprovalRepository(tmp_path)
    repo.save(ApprovalRecord(task_id="task-1", status="pending"))
    repo.save(ApprovalRecord(task_id="task-2", status="approved"))

    result = repo.list_pending()

    assert len(result) == 1
    assert result[0].task_id == "task-1"


def test_save_overwrites_existing_approval(tmp_path: Path) -> None:
    repo = ApprovalRepository(tmp_path)
    repo.save(ApprovalRecord(task_id="task-1", status="pending"))

    repo.save(ApprovalRecord(task_id="task-1", status="approved"))

    assert repo.get("task-1").status == "approved"
