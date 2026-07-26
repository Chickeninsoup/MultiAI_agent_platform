from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.domain.events.event_repository import EventRepository
from src.domain.events.timeline_builder import TimelineBuilder
from src.repositories import RunRepository, TaskRepository
from src.review.change_snapshot import ChangeSnapshot
from src.review.snapshot_repository import SnapshotRepository
from src.run_query_service import RunInspection, RunQueryService


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def _write_task(tasks_dir: Path, task_id: str) -> None:
    _write_json(
        tasks_dir / task_id / "task.json",
        {
            "id": task_id,
            "title": "Test task",
            "description": "A task used for testing.",
            "workspace_id": "workspace-1",
            "status": "in_progress",
            "priority": "normal",
            "created_by": "user-1",
            "assigned_agents": ["agent-test"],
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": None,
            "abandoned_at": None,
            "current_run_id": None,
            "run_count": 0,
            "completion_criteria": [],
            "tags": [],
        },
    )


def _write_run(
    tasks_dir: Path,
    task_id: str,
    run_id: str,
    *,
    status: str = "completed",
) -> None:
    _write_json(
        tasks_dir / task_id / "runs" / run_id / "run.json",
        {
            "id": run_id,
            "task_id": task_id,
            "agent_id": "agent-test",
            "status": status,
            "created_at": "2026-01-01T00:00:00Z",
            "updated_at": "2026-01-01T00:00:00Z",
            "started_at": "2026-01-01T00:00:00Z",
            "completed_at": "2026-01-01T00:00:00Z",
        },
    )


def _build_service(tasks_dir: Path) -> RunQueryService:
    task_repository = TaskRepository(tasks_dir)
    run_repository = RunRepository(tasks_dir)

    return RunQueryService(
        task_repository=task_repository,
        run_repository=run_repository,
        event_repository=EventRepository(),
        snapshot_repository=SnapshotRepository(),
        timeline_builder=TimelineBuilder(),
    )


def test_list_runs_returns_empty_when_no_tasks(
    tmp_path: Path,
) -> None:
    service = _build_service(tmp_path / "tasks")

    assert service.list_runs() == []


def test_list_runs_returns_all_runs_across_tasks(
    tmp_path: Path,
) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "task-a")
    _write_run(tasks_dir, "task-a", "run-001")
    _write_run(tasks_dir, "task-a", "run-002")
    _write_task(tasks_dir, "task-b")
    _write_run(tasks_dir, "task-b", "run-001")

    service = _build_service(tasks_dir)

    runs = service.list_runs()

    assert {(run.task_id, run.id) for run in runs} == {
        ("task-a", "run-001"),
        ("task-a", "run-002"),
        ("task-b", "run-001"),
    }


def test_inspect_run_raises_for_unknown_run_id(
    tmp_path: Path,
) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "task-a")

    service = _build_service(tasks_dir)

    with pytest.raises(ValueError, match="No task owns run"):
        service.inspect_run("run-does-not-exist")


def test_inspect_run_returns_run_and_task_id(
    tmp_path: Path,
) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "task-a")
    _write_run(tasks_dir, "task-a", "run-001", status="awaiting_review")

    service = _build_service(tasks_dir)

    inspection = service.inspect_run("run-001")

    assert isinstance(inspection, RunInspection)
    assert inspection.task_id == "task-a"
    assert inspection.run.id == "run-001"
    assert inspection.run.status == "awaiting_review"


def test_inspect_run_without_events_file_has_empty_timeline(
    tmp_path: Path,
) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "task-a")
    _write_run(tasks_dir, "task-a", "run-001")

    service = _build_service(tasks_dir)

    inspection = service.inspect_run("run-001")

    assert inspection.timeline.run_id == "run-001"
    assert inspection.timeline.events == []


def test_inspect_run_loads_timeline_from_events_file(
    tmp_path: Path,
) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "task-a")
    _write_run(tasks_dir, "task-a", "run-001")

    events_path = tasks_dir / "task-a" / "runs" / "run-001" / "events.jsonl"
    events_path.write_text(
        json.dumps({"type": "tool_call", "name": "read_file"}) + "\n",
        encoding="utf-8",
    )

    service = _build_service(tasks_dir)

    inspection = service.inspect_run("run-001")

    assert [event.event_type for event in inspection.timeline.events] == [
        "tool_call",
    ]


def test_inspect_run_without_snapshot_has_none_snapshot(
    tmp_path: Path,
) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "task-a")
    _write_run(tasks_dir, "task-a", "run-001")

    service = _build_service(tasks_dir)

    inspection = service.inspect_run("run-001")

    assert inspection.snapshot is None


def test_inspect_run_loads_persisted_snapshot(
    tmp_path: Path,
) -> None:
    tasks_dir = tmp_path / "tasks"
    _write_task(tasks_dir, "task-a")
    _write_run(tasks_dir, "task-a", "run-001", status="awaiting_review")

    run_directory = tasks_dir / "task-a" / "runs" / "run-001"
    SnapshotRepository().save(
        run_directory,
        ChangeSnapshot(
            run_id="run-001",
            changed_files=["src/main.py"],
            mutation_count=1,
            test_results={"run_test": {"exit_code": 0}},
            diff_path=None,
        ),
    )

    service = _build_service(tasks_dir)

    inspection = service.inspect_run("run-001")

    assert inspection.snapshot is not None
    assert inspection.snapshot.changed_files == ["src/main.py"]
    assert inspection.snapshot.mutation_count == 1
