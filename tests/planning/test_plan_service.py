from __future__ import annotations

from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.agents.task_agent_team_state import TaskAgentTeamState
from src.planning.plan_record import PlanRecord
from src.planning.plan_service import PlanService
from src.planning.task_planning_context import TaskPlanningContext
from src.task_plan import TaskPlan, TaskStep


class FakePlanRepository:
    def __init__(self) -> None:
        self.saved: PlanRecord | None = None
        self._by_task_id: dict[str, PlanRecord] = {}
        self.pending: list[PlanRecord] = []

    def save(self, record: PlanRecord) -> None:
        self.saved = record
        self._by_task_id[record.task_id] = record

    def get(self, task_id: str) -> PlanRecord | None:
        return self._by_task_id.get(task_id)

    def list_pending(self) -> list[PlanRecord]:
        return self.pending


class FakeReviewService:
    def __init__(self, review) -> None:
        self._review = review
        self.received_plan = None

    def create_review(self, plan):
        self.received_plan = plan
        return self._review


class FakeManagerAgent:
    def __init__(self, plan: TaskPlan) -> None:
        self._plan = plan
        self.received: tuple | None = None

    def plan(self, request, task_id, context=None) -> TaskPlan:
        self.received = (request, task_id, context)
        return self._plan


class FakeContextFactory:
    def __init__(self) -> None:
        self.requested_task_id: str | None = None

    def create(self, task_id: str) -> TaskPlanningContext:
        self.requested_task_id = task_id
        return TaskPlanningContext(
            task_id=task_id, available_agents=[]
        )


def _plan(task_id: str = "task-1") -> TaskPlan:
    return TaskPlan(
        task_id=task_id,
        steps=[
            TaskStep(
                step_id="coding",
                agent_id="agent-coder",
                description="write code",
            )
        ],
    )


def _service(
    review_service=None,
    repo=None,
    manager=None,
    context_factory=None,
    team_lifecycle=None,
) -> PlanService:
    return PlanService(
        review_service if review_service is not None else FakeReviewService(None),
        repo if repo is not None else FakePlanRepository(),
        manager if manager is not None else FakeManagerAgent(_plan()),
        context_factory if context_factory is not None else FakeContextFactory(),
        team_lifecycle
        if team_lifecycle is not None
        else TaskAgentTeamLifecycle(TaskAgentRegistry()),
    )


def test_create_review_delegates_to_review_service() -> None:
    fake_review = object()
    review_service = FakeReviewService(fake_review)
    service = _service(review_service=review_service)
    plan = _plan()

    result = service.create_review(plan)

    assert result is fake_review
    assert review_service.received_plan is plan


def test_save_plan_saves_a_plan_record_via_the_repository() -> None:
    repo = FakePlanRepository()
    service = _service(repo=repo)
    plan = _plan()

    record = service.save_plan(plan)

    assert repo.saved is record
    assert record.plan is plan
    assert record.task_id == "task-1"
    assert record.status == "pending"


def test_get_plan_delegates_to_the_repository() -> None:
    repo = FakePlanRepository()
    service = _service(repo=repo)
    service.save_plan(_plan())

    loaded = service.get_plan("task-1")

    assert loaded is not None
    assert loaded.task_id == "task-1"


def test_get_plan_returns_none_when_missing() -> None:
    service = _service()

    assert service.get_plan("missing") is None


def test_get_pending_plans_delegates_to_the_repository() -> None:
    repo = FakePlanRepository()
    expected = [
        PlanRecord(
            task_id="task-1", plan=_plan(), created_at="now"
        )
    ]
    repo.pending = expected
    service = _service(repo=repo)

    assert service.get_pending_plans() is expected


def test_create_plan_builds_context_from_the_task_id() -> None:
    context_factory = FakeContextFactory()
    manager = FakeManagerAgent(_plan())
    service = _service(manager=manager, context_factory=context_factory)

    service.create_plan("task-1", "implement feature")

    assert context_factory.requested_task_id == "task-1"


def test_create_plan_forwards_request_task_id_and_context_to_the_manager() -> (
    None
):
    context_factory = FakeContextFactory()
    manager = FakeManagerAgent(_plan())
    service = _service(manager=manager, context_factory=context_factory)

    service.create_plan("task-1", "implement feature")

    request, task_id, context = manager.received
    assert request == "implement feature"
    assert task_id == "task-1"
    assert context.task_id == "task-1"
    assert context.available_agents == []


def test_create_plan_persists_and_returns_the_generated_plan() -> None:
    repo = FakePlanRepository()
    plan = _plan("task-1")
    service = _service(repo=repo, manager=FakeManagerAgent(plan))

    record = service.create_plan("task-1", "implement feature")

    assert record.plan is plan
    assert record.status == "pending"
    assert repo.saved is record


def test_create_plan_locks_the_team() -> None:
    lifecycle = TaskAgentTeamLifecycle(TaskAgentRegistry())
    service = _service(team_lifecycle=lifecycle)

    service.create_plan("task-1", "implement feature")

    assert lifecycle.state("task-1") is TaskAgentTeamState.LOCKED


class RecordingManagerAgent:
    def __init__(
        self,
        plan: TaskPlan,
        lifecycle: TaskAgentTeamLifecycle,
    ) -> None:
        self._plan = plan
        self._lifecycle = lifecycle
        self.state_when_called: TaskAgentTeamState | None = None

    def plan(self, request, task_id, context=None) -> TaskPlan:
        self.state_when_called = self._lifecycle.state(task_id)
        return self._plan


def test_create_plan_locks_the_team_before_calling_the_manager() -> (
    None
):
    lifecycle = TaskAgentTeamLifecycle(TaskAgentRegistry())
    manager = RecordingManagerAgent(_plan(), lifecycle)
    service = _service(manager=manager, team_lifecycle=lifecycle)

    service.create_plan("task-1", "implement feature")

    assert manager.state_when_called is TaskAgentTeamState.LOCKED
