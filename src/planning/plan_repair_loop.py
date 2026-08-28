from __future__ import annotations

from src.planning.plan_validator import PlanValidator
from src.planning.planner import Planner
from src.planning.planning_errors import PlanRepairLimitExceeded
from src.planning.task_planning_context import TaskPlanningContext
from src.planning.repair_loop_result import RepairLoopResult
from src.planning.repair_planner import RepairPlanner
from src.planning.repair_preparation_service import (
    RepairPreparationService,
)
from src.task_plan import TaskPlan, TaskStep


class PlanRepairLoop:
    """Runs create -> validate -> repair -> validate until a plan passes.

    Only concerned with plan generation correctness - it never touches
    Scheduler, Approval, or task execution. Stays entirely on the
    "does the LLM output a valid plan" side of the boundary; a valid
    plan is handed back for the existing PlanReviewService/Approval
    flow to take over exactly as before.

    context (Phase 1-F) is resolved once, by the caller, and threaded
    unchanged through every attempt in a run - both the first
    planner.create_plan() call and every repair_preparation_service.
    prepare() call after it. Never re-resolved mid-loop: if the set of
    agents assigned to this task could change between attempt 1 and
    attempt 2, repair semantics stop being deterministic (Claude could
    get told the boundary shifted mid-repair for no reason it caused).
    """

    def __init__(
        self,
        planner: Planner,
        repair_planner: RepairPlanner,
        validator: PlanValidator,
        repair_preparation_service: RepairPreparationService,
        max_attempts: int = 3,
    ) -> None:
        self.planner = planner
        self.repair_planner = repair_planner
        self.validator = validator
        self.repair_preparation_service = repair_preparation_service
        self.max_attempts = max_attempts

    def run(
        self,
        request: str,
        task_id: str,
        context: TaskPlanningContext | None = None,
    ) -> RepairLoopResult:
        plan = self.planner.create_plan(request, task_id, context)
        validation = self.validator.validate(plan)
        attempts = 1

        if validation.valid:
            return RepairLoopResult(
                plan=plan, attempts=attempts, repaired=False
            )

        while attempts < self.max_attempts:
            repair_request = self.repair_preparation_service.prepare(
                plan, validation, context
            )

            if repair_request is None:
                raise PlanRepairLimitExceeded(
                    "Validation errors are not repairable"
                )

            output = self.repair_planner.repair(repair_request)
            plan = TaskPlan(
                task_id=task_id,
                steps=[
                    self._to_task_step(step) for step in output.steps
                ],
            )
            validation = self.validator.validate(plan)
            attempts += 1

            if validation.valid:
                return RepairLoopResult(
                    plan=plan, attempts=attempts, repaired=True
                )

        raise PlanRepairLimitExceeded(
            f"Plan still invalid after {attempts} attempts"
        )

    @staticmethod
    def _to_task_step(step) -> TaskStep:
        return TaskStep(
            step_id=step.step_id,
            agent_id=step.agent_id,
            description=step.description,
            depends_on=step.depends_on,
        )
