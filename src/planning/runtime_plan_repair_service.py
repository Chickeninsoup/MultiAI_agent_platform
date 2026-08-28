from __future__ import annotations

from src.planning.plan_repair_request import PlanRepairRequest
from src.planning.planner_output import PlannerOutput
from src.planning.repair_planner import RepairPlanner


class RuntimePlanRepairService:
    """Thin execution boundary between the Recovery layer and the
    Planning layer (5E-5C-7B) - hands a PlanRepairRequest to
    RepairPlanner and returns exactly what comes back.

    Deliberately does nothing else: no TaskPlan conversion, no Task
    status changes, no PlanValidator, no PlanRepairLoop. Those belong
    to whatever calls this (5E-5C-7C's RecoveryExecutor wiring) or
    stay entirely out of scope (PlanRepairLoop's own create-from-
    scratch loop is a different repair strategy, not reused here -
    see the 5E-5C-7-0 audit). This class exists only so the Recovery
    layer has one narrow adapter to depend on instead of reaching into
    RepairPlanner (a Planning-layer concept) directly.

    repair_planner is a required constructor argument, not an
    internally-created default, matching every other execution-policy
    dependency in this chain (FailureClassifier, FailureRetryClassifier,
    RecoveryPlanner).
    """

    def __init__(self, repair_planner: RepairPlanner) -> None:
        self._repair_planner = repair_planner

    def repair(self, request: PlanRepairRequest) -> PlannerOutput:
        return self._repair_planner.repair(request)
