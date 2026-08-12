from __future__ import annotations

from src.planning.plan_approval_service import PlanApprovalService
from src.planning.plan_review import PlanReview
from src.planning.plan_validation import PlanValidationResult
from src.task_plan import TaskPlan


def _review(*, valid: bool = True) -> PlanReview:
    return PlanReview(
        plan=TaskPlan(task_id="task-1", steps=[]),
        validation=PlanValidationResult(
            valid=valid,
            errors=[] if valid else ["Unknown agent: agent-x"],
            warnings=[],
        ),
        summary="summary",
    )


def test_approve_creates_approved_status() -> None:
    service = PlanApprovalService()
    review = _review()

    approval = service.approve(review)

    assert approval.status == "approved"
    assert approval.review is review


def test_reject_creates_rejected_status() -> None:
    service = PlanApprovalService()
    review = _review()

    approval = service.reject(review)

    assert approval.status == "rejected"
    assert approval.review is review


def test_invalid_review_can_still_be_approved() -> None:
    service = PlanApprovalService()
    review = _review(valid=False)

    approval = service.approve(review)

    assert approval.status == "approved"


def test_valid_review_can_still_be_rejected() -> None:
    service = PlanApprovalService()
    review = _review(valid=True)

    approval = service.reject(review)

    assert approval.status == "rejected"
