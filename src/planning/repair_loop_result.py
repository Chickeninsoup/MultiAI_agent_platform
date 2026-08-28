from __future__ import annotations

from dataclasses import dataclass

from src.task_plan import TaskPlan


@dataclass(frozen=True)
class RepairLoopResult:
    """The outcome of PlanRepairLoop.run(): a valid plan, and how it got there.

    attempts counts every create_plan/repair call that happened (1 if
    the first plan was already valid), repaired is just attempts > 1
    made explicit - a caller/log line shouldn't have to infer "was
    this repaired" from an attempt count.
    """

    plan: TaskPlan
    attempts: int
    repaired: bool
