from __future__ import annotations

from pathlib import Path

from src.planning.plan_record import PlanRecord
from src.repositories import JsonRepository
from src.task_plan import TaskPlan


class PlanRepository:
    """Persists PlanRecords under tasks/<task_id>/plan.json.

    Same directory tree TaskRepository/RunRepository already use
    (tasks_dir passed in), so a task's plan sits alongside its
    task.json/runs/ rather than in a separate planning-only tree.
    """

    def __init__(self, tasks_dir: Path) -> None:
        self._tasks_dir = tasks_dir

    def get_plan_file(self, task_id: str) -> Path:
        return self._tasks_dir / task_id / "plan.json"

    def save(self, record: PlanRecord) -> None:
        JsonRepository.save(
            self.get_plan_file(record.task_id),
            {
                "task_id": record.task_id,
                "plan": record.plan.to_dict(),
                "created_at": record.created_at,
                "status": record.status,
            },
        )

    def get(self, task_id: str) -> PlanRecord | None:
        plan_file = self.get_plan_file(task_id)

        if not plan_file.exists():
            return None

        data = JsonRepository.load(plan_file)

        return PlanRecord(
            task_id=data["task_id"],
            plan=TaskPlan.from_dict(data["plan"]),
            created_at=data["created_at"],
            status=data["status"],
        )

    def exists(self, task_id: str) -> bool:
        return self.get_plan_file(task_id).exists()

    def list_pending(self) -> list[PlanRecord]:
        if not self._tasks_dir.exists():
            return []

        pending: list[PlanRecord] = []

        for task_dir in sorted(self._tasks_dir.iterdir()):
            if not task_dir.is_dir():
                continue

            record = self.get(task_dir.name)

            if record is not None and record.status == "pending":
                pending.append(record)

        return pending
