from __future__ import annotations

from src.planning.plan_review import PlanReview
from src.planning.plan_validation import PlanValidationResult
from src.planning.plan_validator import PlanValidator
from src.task_plan import TaskPlan


class PlanReviewService:
    """Turns a TaskPlan into a PlanReview a human can act on.

    First thing that actually produces a PlanReview (5D-5D-2) - the
    model existed but nothing built one. Summary generation is
    deliberately deterministic string formatting, not an LLM call:
    this sits on the human-review safety boundary, so what a reviewer
    reads must be exactly reproducible from the plan and its
    validation, not a fresh generation each time. Only assembles the
    review - approve/reject/status belongs to 5D-5D-3 Human Approval
    Flow, not this service.
    """

    def __init__(self, validator: PlanValidator) -> None:
        self._validator = validator

    def create_review(self, plan: TaskPlan) -> PlanReview:
        validation = self._validator.validate(plan)
        summary = self._build_summary(plan, validation)

        return PlanReview(
            plan=plan, validation=validation, summary=summary
        )

    def _build_summary(
        self, plan: TaskPlan, validation: PlanValidationResult
    ) -> str:
        lines = [f"Task Plan: {plan.task_id}", ""]

        if validation.valid:
            lines.append("Validation: PASSED")
        else:
            lines.append("Validation: FAILED")
            for message in validation.error_messages():
                lines.append(f"- {message}")

        lines.append("")
        lines.append("Steps:")

        for step in plan.steps:
            lines.append(f"- {step.step_id}")
            lines.append(f"  Agent: {step.agent_id}")
            lines.append(f"  Description: {step.description}")

            if step.depends_on:
                lines.append(
                    "  Depends on: " + ", ".join(step.depends_on)
                )
            else:
                lines.append("  Depends on: None")

        return "\n".join(lines)
