from __future__ import annotations

from dataclasses import dataclass

from src.planning.plan_validation import PlanValidationResult
from src.task_plan import TaskPlan


@dataclass(frozen=True)
class PlanReview:
    """A TaskPlan packaged for a human to look at before it runs.

    Just a domain model (5D-5D-1) - no approved/status/reviewer_id
    fields yet, since nothing consumes an approval decision. Holds the
    plan itself (not just a summary) because what a human approves is
    the concrete TaskPlan, and validation alongside it so a rejected
    or invalid plan is still representable - PlanReview doesn't imply
    the plan passed validation.
    """

    plan: TaskPlan
    validation: PlanValidationResult
    summary: str
