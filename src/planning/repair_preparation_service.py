from __future__ import annotations

from src.planning.plan_repair_request import PlanRepairRequest
from src.planning.plan_validation import PlanValidationResult
from src.planning.repair_decision_service import RepairDecisionService
from src.planning.repair_request_builder import RepairRequestBuilder
from src.planning.task_planning_context import TaskPlanningContext
from src.task_plan import TaskPlan


class RepairPreparationService:
    """Wires RepairDecisionService and RepairRequestBuilder together.

    Nothing downstream should ask RepairRequestBuilder to build a
    request without first checking RepairDecision - this service is
    that single call site, so a caller never has to remember the
    ordering itself. context (Phase 1-F) is forwarded, not resolved -
    same reasoning as RepairRequestBuilder.
    """

    def __init__(
        self,
        decision_service: RepairDecisionService,
        builder: RepairRequestBuilder,
    ) -> None:
        self.decision_service = decision_service
        self.builder = builder

    def prepare(
        self,
        plan: TaskPlan,
        validation: PlanValidationResult,
        context: TaskPlanningContext | None = None,
    ) -> PlanRepairRequest | None:
        decision = self.decision_service.decide(validation)

        if not decision.should_repair:
            return None

        return self.builder.build(plan, validation, context)
