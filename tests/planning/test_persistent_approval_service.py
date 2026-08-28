from __future__ import annotations

from src.planning.approval_record import ApprovalRecord
from src.planning.persistent_approval_service import (
    PersistentApprovalService,
)
from src.planning.plan_review import PlanReview
from src.planning.plan_validation import PlanValidationResult
from src.planning.validation_error import ValidationError
from src.task_plan import TaskPlan


class FakeApprovalRepository:
    def __init__(self) -> None:
        self.saved: ApprovalRecord | None = None

    def save(self, record: ApprovalRecord) -> None:
        self.saved = record


def _review() -> PlanReview:
    return PlanReview(
        plan=TaskPlan(task_id="task-1", steps=[]),
        validation=PlanValidationResult(
            valid=True, errors=[], warnings=[]
        ),
        summary="summary",
    )


def test_approve_and_save() -> None:
    approval_repo = FakeApprovalRepository()
    service = PersistentApprovalService(approval_repo)

    result = service.approve_and_save(_review())

    assert result.status == "approved"
    assert result.task_id == "task-1"
    assert approval_repo.saved is result


def test_reject_and_save() -> None:
    approval_repo = FakeApprovalRepository()
    service = PersistentApprovalService(approval_repo)

    result = service.reject_and_save(_review())

    assert result.status == "rejected"
    assert approval_repo.saved is result


def test_approve_and_save_uses_the_reviews_task_id() -> None:
    approval_repo = FakeApprovalRepository()
    service = PersistentApprovalService(approval_repo)
    review = PlanReview(
        plan=TaskPlan(task_id="task-42", steps=[]),
        validation=PlanValidationResult(
            valid=True, errors=[], warnings=[]
        ),
        summary="summary",
    )

    result = service.approve_and_save(review)

    assert result.task_id == "task-42"


def test_invalid_review_can_still_be_approved_and_saved() -> None:
    approval_repo = FakeApprovalRepository()
    service = PersistentApprovalService(approval_repo)
    review = PlanReview(
        plan=TaskPlan(task_id="task-1", steps=[]),
        validation=PlanValidationResult(
            valid=False,
            errors=[
                ValidationError(
                    code="UNKNOWN_AGENT",
                    message="Unknown agent",
                    repairable=True,
                )
            ],
            warnings=[],
        ),
        summary="summary",
    )

    result = service.approve_and_save(review)

    assert result.status == "approved"
