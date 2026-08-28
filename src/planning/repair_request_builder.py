from __future__ import annotations

from src.planning.plan_repair_request import PlanRepairRequest
from src.planning.plan_validation import PlanValidationResult
from src.planning.repair_request_source import RepairRequestSource
from src.planning.task_planning_context import TaskPlanningContext
from src.task_plan import TaskPlan


class RepairRequestBuilder:
    """Converts a failed PlanValidationResult into a PlanRepairRequest.

    Kept separate from PlanValidator on purpose: the Validator's job
    is to decide whether a plan is valid, not to know how repair
    requests are phrased. Refuses to build a request for an already
    valid plan - there is nothing to repair, and callers (5E-3B-5's
    RepairPreparationService) are expected to check
    RepairDecision.should_repair before ever reaching here. context
    is threaded straight through (Phase 1-F) rather than resolved
    here - the caller (PlanRepairLoop) owns keeping the same
    TaskPlanningContext across every attempt in a run.
    """

    def build(
        self,
        plan: TaskPlan,
        validation: PlanValidationResult,
        context: TaskPlanningContext | None = None,
    ) -> PlanRepairRequest:
        if validation.valid:
            raise ValueError("Cannot repair a valid plan")

        return PlanRepairRequest(
            original_plan=plan,
            errors=validation.errors,
            instructions=self._build_instruction(validation),
            context=context,
            source=RepairRequestSource.VALIDATION,
        )

    def _build_instruction(
        self, validation: PlanValidationResult
    ) -> str:
        return (
            "Fix the validation errors "
            "and generate a new valid plan."
        )
