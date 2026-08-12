from __future__ import annotations

import pytest

import src.main as main
from src.planning.plan_review import PlanReview
from src.planning.plan_validation import PlanValidationResult
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_plan import TaskPlan, TaskStep


class FakeManagerAgent:
    def __init__(self, plan: TaskPlan) -> None:
        self._plan = plan
        self.calls: list[tuple[str, str]] = []

    def plan(self, request: str, task_id: str) -> TaskPlan:
        self.calls.append((request, task_id))
        return self._plan


class FakePlanReviewService:
    def __init__(self, review: PlanReview) -> None:
        self._review = review

    def create_review(self, plan: TaskPlan) -> PlanReview:
        assert plan is self._review.plan
        return self._review


class FakeApprovedPlanExecutor:
    def __init__(self) -> None:
        self.executed_approvals = []

    def execute(self, approval):
        self.executed_approvals.append(approval)
        return [
            StepExecutionResult(
                step_id="coding",
                status=StepStatus.SUCCESS,
                output="done",
            )
        ]


def _plan() -> TaskPlan:
    return TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="coding",
                agent_id="agent-coder",
                description="fix the bug",
            )
        ],
    )


def _review(*, valid: bool = True) -> PlanReview:
    plan = _plan()
    return PlanReview(
        plan=plan,
        validation=PlanValidationResult(
            valid=valid,
            errors=[] if valid else ["Unknown agent: agent-x"],
            warnings=[],
        ),
        summary=f"Task Plan: {plan.task_id}",
    )


def _wire(monkeypatch: pytest.MonkeyPatch, review: PlanReview):
    manager = FakeManagerAgent(review.plan)
    executor = FakeApprovedPlanExecutor()

    monkeypatch.setattr(main, "manager_agent", manager)
    monkeypatch.setattr(
        main, "plan_review_service", FakePlanReviewService(review)
    )
    monkeypatch.setattr(main, "approved_plan_executor", executor)

    return manager, executor


def test_approving_a_valid_plan_executes_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    manager, executor = _wire(monkeypatch, _review(valid=True))
    monkeypatch.setattr("builtins.input", lambda _: "y")

    main.plan_task("task-001", "fix the bug")

    assert manager.calls == [("fix the bug", "task-001")]
    assert len(executor.executed_approvals) == 1
    assert executor.executed_approvals[0].status == "approved"


def test_rejecting_a_plan_does_not_execute_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, executor = _wire(monkeypatch, _review(valid=True))
    monkeypatch.setattr("builtins.input", lambda _: "n")

    main.plan_task("task-001", "fix the bug")

    assert executor.executed_approvals == []


def test_invalid_plan_can_still_be_approved(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, executor = _wire(monkeypatch, _review(valid=False))
    monkeypatch.setattr("builtins.input", lambda _: "y")

    main.plan_task("task-001", "fix the bug")

    assert len(executor.executed_approvals) == 1
    assert executor.executed_approvals[0].status == "approved"


def test_invalid_plan_prompts_with_an_override_warning(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch, _review(valid=False))
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return "n"

    monkeypatch.setattr("builtins.input", fake_input)

    main.plan_task("task-001", "fix the bug")

    assert len(prompts) == 1
    assert "Override" in prompts[0]


def test_valid_plan_prompts_with_a_plain_approve_question(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _wire(monkeypatch, _review(valid=True))
    prompts: list[str] = []

    def fake_input(prompt: str) -> str:
        prompts.append(prompt)
        return "n"

    monkeypatch.setattr("builtins.input", fake_input)

    main.plan_task("task-001", "fix the bug")

    assert prompts == ["Approve? [y/N]: "]


def test_any_non_y_answer_rejects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, executor = _wire(monkeypatch, _review(valid=True))
    monkeypatch.setattr("builtins.input", lambda _: "")

    main.plan_task("task-001", "fix the bug")

    assert executor.executed_approvals == []
