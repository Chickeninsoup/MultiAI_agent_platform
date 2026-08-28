from __future__ import annotations

import dataclasses

from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.clock import utc_now
from src.manager_agent import ManagerAgent
from src.planning.plan_record import PlanRecord
from src.planning.plan_repository import PlanRepository
from src.planning.plan_review import PlanReview
from src.planning.plan_review_service import PlanReviewService
from src.planning.planning_errors import PlanNotFoundError
from src.planning.task_planning_context_factory import (
    TaskPlanningContextFactory,
)
from src.task_plan import TaskPlan


class PlanService:
    """The only thing CLI/other callers should touch to generate/persist a plan.

    Matches this codebase's existing TaskService/RunService style:
    a thin orchestration layer between a caller and a Repository, so
    nothing outside src/planning/ needs to know PlanRepository exists
    or what a plan.json looks like on disk. manager_agent and
    context_factory are required (Phase 1C-4), not optional - a
    caller that doesn't wire a real TaskPlanningContextFactory
    shouldn't be able to silently fall back to context-free planning;
    that would just reintroduce the global-agent-pool assumption this
    whole Task-scoped Agent redesign exists to remove.

    team_lifecycle.lock() (5E-4B) runs before context_factory.create()
    in create_plan(), not after - locking after reading the team would
    leave a window where an assignment lands between "context built"
    and "team locked," so the context a Planner sees could already be
    stale relative to what's actually locked in. No automatic unlock
    on planning failure: unlock semantics aren't defined yet, and
    auto-unlocking would let a retried planning attempt see a
    different team than the one that failed, breaking the whole point
    of locking the team before a planning transaction starts.
    """

    def __init__(
        self,
        review_service: PlanReviewService,
        plan_repository: PlanRepository,
        manager_agent: ManagerAgent,
        context_factory: TaskPlanningContextFactory,
        team_lifecycle: TaskAgentTeamLifecycle,
    ) -> None:
        self._review_service = review_service
        self._plan_repository = plan_repository
        self._manager_agent = manager_agent
        self._context_factory = context_factory
        self._team_lifecycle = team_lifecycle

    def create_plan(self, task_id: str, request: str) -> PlanRecord:
        self._team_lifecycle.lock(task_id)
        context = self._context_factory.create(task_id)
        plan = self._manager_agent.plan(request, task_id, context)

        return self.save_plan(plan)

    def create_review(self, plan: TaskPlan) -> PlanReview:
        return self._review_service.create_review(plan)

    def save_plan(self, plan: TaskPlan) -> PlanRecord:
        record = PlanRecord(
            task_id=plan.task_id,
            plan=plan,
            created_at=utc_now(),
        )
        self._plan_repository.save(record)

        return record

    def get_plan(self, task_id: str) -> PlanRecord | None:
        return self._plan_repository.get(task_id)

    def get_pending_plans(self) -> list[PlanRecord]:
        return self._plan_repository.list_pending()

    def update_status(self, task_id: str, status: str) -> PlanRecord:
        record = self._plan_repository.get(task_id)

        if record is None:
            raise PlanNotFoundError(
                f"No plan found for task: {task_id}"
            )

        updated = dataclasses.replace(record, status=status)
        self._plan_repository.save(updated)

        return updated
