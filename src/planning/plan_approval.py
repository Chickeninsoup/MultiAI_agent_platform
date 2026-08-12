from __future__ import annotations

from dataclasses import dataclass

from src.planning.plan_review import PlanReview


@dataclass(frozen=True)
class PlanApproval:
    """A PlanReview plus a human's decision on it.

    status is a plain str ("pending" / "approved" / "rejected"), not
    an Enum, to match how RunDefinition.status is modeled elsewhere in
    this codebase - a wider status vocabulary can be unified later if
    it grows past this. Deliberately no approve()/reject() methods: a
    frozen model doesn't change its own state, and no approve_by,
    approved_at, or execution_id fields either, since there's no user
    system or persistence layer yet for this to plug into. Producing
    an approved/rejected PlanApproval from a "pending" one is
    5D-5D-3B's job (PlanApprovalService), not this dataclass's.
    """

    review: PlanReview
    status: str = "pending"
