from __future__ import annotations

from src.planning.approval_record import ApprovalRecord
from src.planning.approval_repository import ApprovalRepository
from src.planning.plan_approval_service import PlanApprovalService
from src.planning.plan_review import PlanReview


class PersistentApprovalService:
    """Wraps PlanApprovalService with disk persistence.

    PlanApprovalService.approve()/reject() are untouched - this
    doesn't replace them, it calls them and then persists an
    ApprovalRecord reflecting the same decision. Anything already
    using PlanApprovalService directly (e.g. ApprovedPlanExecutor's
    in-memory flow from 5D-5D) keeps working exactly as before.
    """

    def __init__(
        self,
        approval_repository: ApprovalRepository,
        approval_service: PlanApprovalService | None = None,
    ) -> None:
        self._approval_repository = approval_repository
        self._approval_service = (
            approval_service
            if approval_service is not None
            else PlanApprovalService()
        )

    def approve_and_save(self, review: PlanReview) -> ApprovalRecord:
        approval = self._approval_service.approve(review)

        return self._save(review, approval.status)

    def reject_and_save(self, review: PlanReview) -> ApprovalRecord:
        approval = self._approval_service.reject(review)

        return self._save(review, approval.status)

    def _save(self, review: PlanReview, status: str) -> ApprovalRecord:
        record = ApprovalRecord(
            task_id=review.plan.task_id, status=status
        )
        self._approval_repository.save(record)

        return record
