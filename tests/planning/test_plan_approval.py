from __future__ import annotations

import dataclasses

import pytest

from src.planning.plan_approval import PlanApproval
from src.planning.plan_review import PlanReview
from src.planning.plan_validation import PlanValidationResult
from src.task_plan import TaskPlan


def _review() -> PlanReview:
    return PlanReview(
        plan=TaskPlan(task_id="task-1", steps=[]),
        validation=PlanValidationResult(
            valid=True, errors=[], warnings=[]
        ),
        summary="summary",
    )


def test_default_status_is_pending() -> None:
    approval = PlanApproval(review=_review())

    assert approval.status == "pending"


def test_plan_approval_holds_the_same_review_instance() -> None:
    review = _review()

    approval = PlanApproval(review=review)

    assert approval.review is review


def test_status_can_be_set_to_approved() -> None:
    approval = PlanApproval(review=_review(), status="approved")

    assert approval.status == "approved"


def test_status_can_be_set_to_rejected() -> None:
    approval = PlanApproval(review=_review(), status="rejected")

    assert approval.status == "rejected"


def test_plan_approval_is_frozen() -> None:
    approval = PlanApproval(review=_review())

    with pytest.raises(dataclasses.FrozenInstanceError):
        approval.status = "approved"
