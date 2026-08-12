from __future__ import annotations

from src.planning.plan_approval import PlanApproval
from src.planning.plan_review import PlanReview


class PlanApprovalService:
    """Records a human's approve/reject decision on a PlanReview.

    Deliberately does not gate on review.validation.valid - an invalid
    plan can still be approved. PlanValidator already surfaced the
    problems in the review a human is looking at; second-guessing
    their decision here would take the final call away from the
    person this whole Human Approval Flow exists to keep in the loop.
    """

    def approve(self, review: PlanReview) -> PlanApproval:
        return PlanApproval(review=review, status="approved")

    def reject(self, review: PlanReview) -> PlanApproval:
        return PlanApproval(review=review, status="rejected")
