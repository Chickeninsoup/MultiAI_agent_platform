from __future__ import annotations

from dataclasses import dataclass, field

from src.clock import utc_now


@dataclass(frozen=True)
class ApprovalRecord:
    """A human's decision on a task's plan, persisted to disk.

    Deliberately doesn't hold the PlanReview/TaskPlan itself - it's
    keyed by task_id, and PlanRepository is the source of truth for
    what plan a task_id refers to. Keeping this record narrow (just
    the decision) means approving doesn't require re-persisting the
    whole plan alongside it. created_at defaults via utc_now (the
    same clock helper task_service.py/run_service.py already use) so
    callers constructing a fresh pending record don't need to supply
    a timestamp themselves.
    """

    task_id: str
    created_at: str = field(default_factory=utc_now)
    status: str = "pending"
