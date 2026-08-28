from __future__ import annotations

from src.agent_runtime_factory import AgentRuntimeFactory
from src.agents.task_agent_registry import TaskAgentRegistry
from src.failure_classifier import FailureClassifier
from src.message_router import MessageRouter
from src.planning.approval_repository import ApprovalRepository
from src.planning.approved_plan_executor import ApprovedPlanExecutor
from src.planning.plan_approval import PlanApproval
from src.planning.plan_execution_result import PlanExecutionResult
from src.planning.plan_repository import PlanRepository
from src.planning.plan_review_service import PlanReviewService
from src.planning.planning_errors import (
    ApprovalNotFoundError,
    PlanNotFoundError,
)
from src.task_dependency_resolver import TaskDependencyResolver
from src.task_plan_converter import TaskPlanConverter
from src.task_plan_executor import TaskPlanExecutor
from src.task_scheduler import TaskScheduler


class PlanExecutionService:
    """Resumes execution of a plan purely from what's on disk.

    The point of this class: a plan can be created in one process
    (`plan` CLI command) and approved in a completely different one,
    possibly a different day (`approve-plan` CLI command) - neither
    process needs to still be running, or share any in-memory state,
    for execution to happen. Only task_id crosses that gap.

    Re-runs PlanReviewService on the persisted TaskPlan rather than
    persisting the original PlanReview - PlanRecord only stores the
    plan (5D-6B-1), not its review, and re-validating right before
    execution is arguably safer anyway (the environment - which
    agents exist, etc. - may have changed since the plan was first
    reviewed).

    Builds a fresh MessageRouter/TaskPlanExecutor/TaskScheduler/
    ApprovedPlanExecutor chain on every execute() call (5E-4D-2)
    instead of taking a single pre-built ApprovedPlanExecutor -
    AgentRuntimeFactory.create_handlers() is now task-scoped, so the
    set of reachable Agent handlers has to be resolved per task_id,
    not once at process startup before any task_id exists. Those four
    classes' own code is untouched; only when/how often they get
    constructed changed. task_agent_registry (5E-4D-3) is an explicit
    dependency here, not reached into via agent_runtime_factory's
    private state - MessageRouter's dispatch-authorization check needs
    it directly.

    execute() returns PlanExecutionResult, not the raw
    list[StepExecutionResult] ApprovedPlanExecutor hands back (5E-4C-1
    Step 2) - this is the one place that aggregates "did the whole
    plan succeed," so every caller gets that answer instead of each
    reimplementing its own all()-over-statuses check.
    """

    def __init__(
        self,
        plan_repository: PlanRepository,
        approval_repository: ApprovalRepository,
        review_service: PlanReviewService,
        agent_runtime_factory: AgentRuntimeFactory,
        task_agent_registry: TaskAgentRegistry,
        task_dependency_resolver: TaskDependencyResolver,
        task_plan_converter: TaskPlanConverter,
    ) -> None:
        self._plan_repository = plan_repository
        self._approval_repository = approval_repository
        self._review_service = review_service
        self._agent_runtime_factory = agent_runtime_factory
        self._task_agent_registry = task_agent_registry
        self._task_dependency_resolver = task_dependency_resolver
        self._task_plan_converter = task_plan_converter

    def execute(self, task_id: str) -> PlanExecutionResult:
        plan_record = self._plan_repository.get(task_id)

        if plan_record is None:
            raise PlanNotFoundError(
                f"No plan found for task: {task_id}"
            )

        approval_record = self._approval_repository.get(task_id)

        if approval_record is None:
            raise ApprovalNotFoundError(
                f"No approval found for task: {task_id}"
            )

        review = self._review_service.create_review(plan_record.plan)
        approval = PlanApproval(
            review=review, status=approval_record.status
        )

        approved_plan_executor = self._build_executor(task_id)
        step_results = approved_plan_executor.execute(approval)

        return PlanExecutionResult(step_results=step_results)

    def _build_executor(self, task_id: str) -> ApprovedPlanExecutor:
        handlers = self._agent_runtime_factory.create_handlers(task_id)
        router = MessageRouter(handlers, self._task_agent_registry)
        executor = TaskPlanExecutor(self._task_plan_converter, router)
        scheduler = TaskScheduler(
            self._task_dependency_resolver,
            executor,
            FailureClassifier(),
        )

        return ApprovedPlanExecutor(scheduler)
