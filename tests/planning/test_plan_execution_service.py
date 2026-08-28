from __future__ import annotations

import pytest

from src.agent_message import AgentMessage
from src.agents.task_agent import TaskAgent
from src.agents.task_agent_registry import TaskAgentRegistry
from src.planning.approval_record import ApprovalRecord
from src.planning.plan_execution_result import PlanExecutionResult
from src.planning.plan_execution_service import (
    ApprovalNotFoundError,
    PlanExecutionService,
    PlanNotFoundError,
)
from src.planning.plan_record import PlanRecord
from src.planning.plan_review import PlanReview
from src.planning.plan_validation import PlanValidationResult
from src.step_execution_result import StepStatus
from src.task_dependency_resolver import TaskDependencyResolver
from src.task_plan import TaskPlan, TaskStep
from src.task_plan_converter import TaskPlanConverter


class FakePlanRepository:
    def __init__(self, record: PlanRecord | None) -> None:
        self._record = record

    def get(self, task_id: str) -> PlanRecord | None:
        return self._record


class FakeApprovalRepository:
    def __init__(self, record: ApprovalRecord | None) -> None:
        self._record = record

    def get(self, task_id: str) -> ApprovalRecord | None:
        return self._record


class FakeReviewService:
    def __init__(self) -> None:
        self.received_plan = None

    def create_review(self, plan: TaskPlan) -> PlanReview:
        self.received_plan = plan
        return PlanReview(
            plan=plan,
            validation=PlanValidationResult(
                valid=True, errors=[], warnings=[]
            ),
            summary="summary",
        )


class FakeAgentHandler:
    """A minimal AgentHandler: responds with a fixed string, or raises
    a fixed exception - enough to drive TaskScheduler/TaskPlanExecutor
    through a real success or failure path without any real Agent
    infrastructure."""

    def __init__(
        self,
        agent_id: str,
        response: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self._agent_id = agent_id
        self._response = response
        self._error = error

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def handle(self, message: AgentMessage) -> str:
        if self._error is not None:
            raise self._error

        assert self._response is not None
        return self._response


class FakeAgentRuntimeFactory:
    def __init__(self, handlers: list[FakeAgentHandler]) -> None:
        self._handlers = handlers
        self.requested_task_ids: list[str] = []

    def create_handlers(
        self, task_id: str
    ) -> list[FakeAgentHandler]:
        self.requested_task_ids.append(task_id)
        return self._handlers


def _plan() -> TaskPlan:
    return TaskPlan(
        task_id="task-1",
        steps=[
            TaskStep(
                step_id="coding",
                agent_id="agent-coder",
                description="write code",
            )
        ],
    )


def _task_agent_registry(
    handlers: list[FakeAgentHandler], task_id: str = "task-1"
) -> TaskAgentRegistry:
    registry = TaskAgentRegistry()

    for handler in handlers:
        registry.assign_agent(
            TaskAgent(
                agent_id=handler.agent_id,
                task_id=task_id,
                template_id="t",
            )
        )

    return registry


def _service(
    plan_repo: FakePlanRepository | None = None,
    approval_repo: FakeApprovalRepository | None = None,
    review_service: FakeReviewService | None = None,
    handlers: list[FakeAgentHandler] | None = None,
) -> PlanExecutionService:
    handlers = handlers or []

    return PlanExecutionService(
        plan_repo if plan_repo is not None else FakePlanRepository(None),
        approval_repo
        if approval_repo is not None
        else FakeApprovalRepository(None),
        review_service if review_service is not None else FakeReviewService(),
        FakeAgentRuntimeFactory(handlers),
        _task_agent_registry(handlers),
        TaskDependencyResolver(),
        TaskPlanConverter(),
    )


def test_execute_reconstructs_approval_and_runs_the_plan() -> None:
    plan_repo = FakePlanRepository(
        PlanRecord(task_id="task-1", plan=_plan(), created_at="now")
    )
    approval_repo = FakeApprovalRepository(
        ApprovalRecord(task_id="task-1", status="approved")
    )
    review_service = FakeReviewService()
    handler = FakeAgentHandler("agent-coder", response="done")
    service = _service(plan_repo, approval_repo, review_service, [handler])

    result = service.execute("task-1")

    assert isinstance(result, PlanExecutionResult)
    assert result.succeeded is True
    assert result.step_results[0].status == StepStatus.SUCCESS
    assert result.step_results[0].output == "done"
    assert review_service.received_plan.task_id == "task-1"


def test_execute_wraps_failed_step_results() -> None:
    plan_repo = FakePlanRepository(
        PlanRecord(task_id="task-1", plan=_plan(), created_at="now")
    )
    approval_repo = FakeApprovalRepository(
        ApprovalRecord(task_id="task-1", status="approved")
    )
    handler = FakeAgentHandler("agent-coder", error=RuntimeError("boom"))
    service = _service(
        plan_repo, approval_repo, FakeReviewService(), [handler]
    )

    result = service.execute("task-1")

    assert isinstance(result, PlanExecutionResult)
    assert result.succeeded is False
    assert result.step_results[0].status == StepStatus.FAILED


def test_execute_raises_when_plan_is_missing() -> None:
    service = _service(
        plan_repo=FakePlanRepository(None),
        approval_repo=FakeApprovalRepository(
            ApprovalRecord(task_id="task-1", status="approved")
        ),
    )

    with pytest.raises(PlanNotFoundError):
        service.execute("task-1")


def test_execute_raises_when_approval_is_missing() -> None:
    service = _service(
        plan_repo=FakePlanRepository(
            PlanRecord(task_id="task-1", plan=_plan(), created_at="now")
        ),
        approval_repo=FakeApprovalRepository(None),
    )

    with pytest.raises(ApprovalNotFoundError):
        service.execute("task-1")


def test_execute_rejects_a_pending_approval() -> None:
    # PlanExecutionService itself doesn't gate on status - it just
    # rebuilds the PlanApproval; the real ApprovedPlanExecutor it
    # builds internally is still the one place that enforces "must be
    # approved."
    service = _service(
        plan_repo=FakePlanRepository(
            PlanRecord(task_id="task-1", plan=_plan(), created_at="now")
        ),
        approval_repo=FakeApprovalRepository(
            ApprovalRecord(task_id="task-1", status="pending")
        ),
        handlers=[FakeAgentHandler("agent-coder", response="done")],
    )

    with pytest.raises(ValueError, match="has not been approved"):
        service.execute("task-1")


def test_execute_requests_handlers_scoped_to_the_task_id() -> None:
    plan_repo = FakePlanRepository(
        PlanRecord(task_id="task-1", plan=_plan(), created_at="now")
    )
    approval_repo = FakeApprovalRepository(
        ApprovalRecord(task_id="task-1", status="approved")
    )
    handler = FakeAgentHandler("agent-coder", response="done")
    runtime_factory = FakeAgentRuntimeFactory([handler])
    service = PlanExecutionService(
        plan_repo,
        approval_repo,
        FakeReviewService(),
        runtime_factory,
        _task_agent_registry([handler]),
        TaskDependencyResolver(),
        TaskPlanConverter(),
    )

    service.execute("task-1")

    assert runtime_factory.requested_task_ids == ["task-1"]
