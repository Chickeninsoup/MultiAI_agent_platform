from __future__ import annotations

from dataclasses import dataclass

from src.task_plan import TaskPlan


@dataclass(frozen=True)
class PlanRecord:
    """A TaskPlan persisted to disk, waiting on a human decision.

    status is a plain str, matching RunDefinition.status and
    PlanApproval.status elsewhere in this codebase rather than an
    Enum. A record's status only ever changes by creating a new
    PlanRecord (frozen) - PlanRepository.save() overwrites the stored
    file, it never mutates a loaded record in place.
    """

    task_id: str
    plan: TaskPlan
    created_at: str
    status: str = "pending"
