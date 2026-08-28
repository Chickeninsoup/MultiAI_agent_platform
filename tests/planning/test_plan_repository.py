from __future__ import annotations

from pathlib import Path

from src.planning.plan_record import PlanRecord
from src.planning.plan_repository import PlanRepository
from src.task_plan import TaskPlan, TaskStep


def _repo(tmp_path: Path) -> PlanRepository:
    return PlanRepository(tmp_path)


def _record(task_id: str = "task-1", status: str = "pending") -> PlanRecord:
    return PlanRecord(
        task_id=task_id,
        plan=TaskPlan(
            task_id=task_id,
            steps=[
                TaskStep(
                    step_id="coding",
                    agent_id="agent-coder",
                    description="write code",
                )
            ],
        ),
        created_at="2026-08-13T00:00:00Z",
        status=status,
    )


def test_save_and_get(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    record = _record()

    repo.save(record)
    loaded = repo.get("task-1")

    assert loaded == record


def test_missing_returns_none(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    assert repo.get("missing") is None


def test_exists(tmp_path: Path) -> None:
    repo = _repo(tmp_path)

    assert repo.exists("task-1") is False

    repo.save(_record())

    assert repo.exists("task-1") is True


def test_list_pending_only_returns_pending_records(
    tmp_path: Path,
) -> None:
    repo = _repo(tmp_path)
    repo.save(_record("task-1", status="pending"))
    repo.save(_record("task-2", status="approved"))
    repo.save(_record("task-3", status="pending"))

    pending = repo.list_pending()

    assert {record.task_id for record in pending} == {"task-1", "task-3"}


def test_list_pending_empty_when_no_tasks_dir(tmp_path: Path) -> None:
    repo = PlanRepository(tmp_path / "does-not-exist")

    assert repo.list_pending() == []


def test_save_overwrites_existing_record(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    repo.save(_record("task-1", status="pending"))

    repo.save(_record("task-1", status="approved"))

    loaded = repo.get("task-1")
    assert loaded is not None
    assert loaded.status == "approved"


def test_plan_survives_the_round_trip_intact(tmp_path: Path) -> None:
    repo = _repo(tmp_path)
    record = _record()

    repo.save(record)
    loaded = repo.get("task-1")

    assert loaded is not None
    assert loaded.plan == record.plan
