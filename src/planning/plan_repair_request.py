from __future__ import annotations

from dataclasses import dataclass, field

from src.planning.repair_request_source import RepairRequestSource
from src.planning.task_planning_context import TaskPlanningContext
from src.planning.validation_error import ValidationError
from src.task_plan import TaskPlan


@dataclass(frozen=True)
class PlanRepairRequest:
    """A structured ask to fix a plan, either because it failed
    validation or because it failed at runtime (5E-5C-7A).

    Carries original_plan (not just the errors) because a repair
    prompt needs to show what was actually wrong with - e.g. "step B
    depends on step A" plus "Unknown agent: agent-python" only makes
    sense together. context is TaskPlanningContext (Phase 1-F) because
    repair is still planning: the same Task-scoped available_agents/
    constraints a Planner needs to build a plan, it also needs to fix
    one - and it must be the *same* boundary, not a freshly-resolved
    one (see PlanRepairLoop, which threads one context through every
    repair attempt in a run).

    source defaults to VALIDATION for backward compatibility - every
    existing caller (RepairRequestBuilder, PlanRepairLoop) already
    means "the plan failed PlanValidator," so nothing has to change to
    keep meaning that. FailureRepairRequestBuilder (5E-5C-7A) is the
    only place that sets EXECUTION_FAILURE explicitly.
    """

    original_plan: TaskPlan
    errors: list[ValidationError] = field(default_factory=list)
    instructions: str = ""
    context: TaskPlanningContext | None = None
    source: RepairRequestSource = RepairRequestSource.VALIDATION

    def summarize(self) -> str:
        lines = ["Original plan failed validation."]

        for error in self.errors:
            lines.append(f"{error.code}: {error.message}")

        lines.append(self.instructions)

        return "\n".join(lines)
