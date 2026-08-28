from __future__ import annotations

import dataclasses

import pytest

from src.planning.repair_loop_result import RepairLoopResult
from src.task_plan import TaskPlan


def test_successful_first_attempt() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])

    result = RepairLoopResult(plan=plan, attempts=1, repaired=False)

    assert result.plan is plan
    assert result.attempts == 1
    assert result.repaired is False


def test_successful_after_repair() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])

    result = RepairLoopResult(plan=plan, attempts=2, repaired=True)

    assert result.attempts == 2
    assert result.repaired is True


def test_frozen() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])
    result = RepairLoopResult(plan=plan, attempts=1, repaired=False)

    with pytest.raises(dataclasses.FrozenInstanceError):
        result.attempts = 2
