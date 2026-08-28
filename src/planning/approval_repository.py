from __future__ import annotations

from pathlib import Path

from src.planning.approval_record import ApprovalRecord
from src.repositories import JsonRepository


class ApprovalRepository:
    """Persists ApprovalRecords under tasks/<task_id>/approval.json.

    Deliberately a separate file from plan.json (not a field inside
    it) - a plan and its approval decision have different lifecycles
    (a plan is written once by planning, the approval is written
    later by a human, possibly in a different process/session), and
    keeping them in separate files means approving never requires
    re-reading or re-writing the (potentially large) plan payload.
    """

    def __init__(self, tasks_dir: Path) -> None:
        self._tasks_dir = tasks_dir

    def get_approval_file(self, task_id: str) -> Path:
        return self._tasks_dir / task_id / "approval.json"

    def save(self, record: ApprovalRecord) -> None:
        JsonRepository.save(
            self.get_approval_file(record.task_id),
            {
                "task_id": record.task_id,
                "created_at": record.created_at,
                "status": record.status,
            },
        )

    def get(self, task_id: str) -> ApprovalRecord | None:
        approval_file = self.get_approval_file(task_id)

        if not approval_file.exists():
            return None

        data = JsonRepository.load(approval_file)

        return ApprovalRecord(
            task_id=data["task_id"],
            created_at=data["created_at"],
            status=data["status"],
        )

    def list_pending(self) -> list[ApprovalRecord]:
        if not self._tasks_dir.exists():
            return []

        pending: list[ApprovalRecord] = []

        for task_dir in sorted(self._tasks_dir.iterdir()):
            if not task_dir.is_dir():
                continue

            record = self.get(task_dir.name)

            if record is not None and record.status == "pending":
                pending.append(record)

        return pending
