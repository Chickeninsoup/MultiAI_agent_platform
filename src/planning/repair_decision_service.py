from __future__ import annotations

from src.planning.plan_validation import PlanValidationResult
from src.planning.repair_decision import RepairDecision


class RepairDecisionService:
    """Turns a PlanValidationResult into a should-we-repair decision.

    Deliberately not a method on PlanValidator or Planner - "does this
    validation result warrant a repair attempt" is a policy question,
    separate from "is the plan valid" (PlanValidator's job) and "how
    do we ask the Planner to try again" (5E-3B/C). Doesn't call
    Claude, doesn't touch TaskPlan, doesn't loop - just classifies.
    """

    def decide(
        self, validation: PlanValidationResult
    ) -> RepairDecision:
        if validation.valid:
            return RepairDecision(False, "Plan already valid")

        if validation.repairable:
            return RepairDecision(
                True, "Validation errors are repairable"
            )

        return RepairDecision(
            False, "Validation errors are not repairable"
        )
