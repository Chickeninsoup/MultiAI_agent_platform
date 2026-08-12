from __future__ import annotations

import dataclasses

import pytest

from src.planning.plan_review import PlanReview
from src.planning.plan_validation import PlanValidationResult
from src.task_plan import TaskPlan


def test_plan_review_holds_plan_validation_and_summary() -> None:
    plan = TaskPlan(task_id="task-1", steps=[])
    validation = PlanValidationResult(valid=True, errors=[], warnings=[])

    review = PlanReview(
        plan=plan, validation=validation, summary="test summary"
    )

    assert review.plan == plan
    assert review.validation == validation
    assert review.summary == "test summary"


def test_plan_review_is_frozen() -> None:
    review = PlanReview(
        plan=TaskPlan(task_id="task-1", steps=[]),
        validation=PlanValidationResult(
            valid=True, errors=[], warnings=[]
        ),
        summary="summary",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        review.summary = "changed"


def test_plan_review_can_hold_an_invalid_validation() -> None:
    validation = PlanValidationResult(
        valid=False, errors=["Unknown agent"], warnings=[]
    )

    review = PlanReview(
        plan=TaskPlan(task_id="task-1", steps=[]),
        validation=validation,
        summary="invalid",
    )

    assert review.validation.valid is False
    assert review.validation.errors == ["Unknown agent"]
