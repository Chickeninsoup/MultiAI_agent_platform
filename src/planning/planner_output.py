from __future__ import annotations

from dataclasses import dataclass, field

from src.planning.plan_schema import PlannedStep


@dataclass(frozen=True)
class PlannerOutput:
    """A Planner's raw structured output - a list of PlannedSteps.

    Not TaskPlan: TaskPlan is the trusted internal model (has a
    task_id, is what Validator/Scheduler/Executor operate on).
    PlannerOutput is what came back from an external source (Claude's
    JSON response) before anything has decided to trust it - it
    doesn't even have a task_id, since that's caller-supplied context
    the LLM never sees a reason to echo back.
    """

    steps: list[PlannedStep] = field(default_factory=list)
