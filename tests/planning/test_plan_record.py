from __future__ import annotations

import dataclasses

import pytest

from src.planning.plan_record import PlanRecord
from src.task_plan import TaskPlan


def make_plan() -> TaskPlan:
    return TaskPlan(task_id="task-1", steps=[])


def test_plan_record_creation() -> None:
    plan = make_plan()

    record = PlanRecord(
        task_id="task-1",
        plan=plan,
        created_at="2026-08-13T00:00:00Z",
    )

    assert record.task_id == "task-1"
    assert record.plan == plan
    assert record.created_at == "2026-08-13T00:00:00Z"


def test_plan_record_defaults_to_pending() -> None:
    record = PlanRecord(
        task_id="task-1",
        plan=make_plan(),
        created_at="2026-08-13T00:00:00Z",
    )

    assert record.status == "pending"


def test_plan_record_can_hold_a_different_status() -> None:
    record = PlanRecord(
        task_id="task-1",
        plan=make_plan(),
        created_at="2026-08-13T00:00:00Z",
        status="executed",
    )

    assert record.status == "executed"


def test_plan_record_is_frozen() -> None:
    record = PlanRecord(
        task_id="task-1",
        plan=make_plan(),
        created_at="2026-08-13T00:00:00Z",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        record.status = "approved"


def test_status_change_produces_a_new_record() -> None:
    record = PlanRecord(
        task_id="task-1",
        plan=make_plan(),
        created_at="2026-08-13T00:00:00Z",
    )

    updated = dataclasses.replace(record, status="approved")

    assert record.status == "pending"
    assert updated.status == "approved"
    assert updated is not record
