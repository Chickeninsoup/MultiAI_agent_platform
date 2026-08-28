from __future__ import annotations

import dataclasses

import pytest

import src.main as main
from src.planning.approval_record import ApprovalRecord
from src.planning.plan_execution_result import PlanExecutionResult
from src.planning.plan_record import PlanRecord
from src.planning.plan_review import PlanReview
from src.planning.plan_validation import PlanValidationResult
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_plan import TaskPlan, TaskStep


class FakePlanService:
    def __init__(self, plan: TaskPlan) -> None:
        self._plan = plan
        self._plans: dict[str, PlanRecord] = {}
        self.pending: list[PlanRecord] = []
        self.review_calls: list[TaskPlan] = []
        self.status_updates: list[tuple[str, str]] = []
        self.create_plan_calls: list[tuple[str, str]] = []

    def create_plan(self, task_id: str, request: str) -> PlanRecord:
        self.create_plan_calls.append((task_id, request))

        return self.save_plan(self._plan)

    def create_review(self, plan: TaskPlan) -> PlanReview:
        self.review_calls.append(plan)
        return PlanReview(
            plan=plan,
            validation=PlanValidationResult(
                valid=True, errors=[], warnings=[]
            ),
            summary=f"Task Plan: {plan.task_id}",
        )

    def save_plan(self, plan: TaskPlan) -> PlanRecord:
        record = PlanRecord(
            task_id=plan.task_id, plan=plan, created_at="now"
        )
        self._plans[plan.task_id] = record

        return record

    def get_plan(self, task_id: str) -> PlanRecord | None:
        return self._plans.get(task_id)

    def get_pending_plans(self) -> list[PlanRecord]:
        return self.pending

    def update_status(self, task_id: str, status: str) -> PlanRecord:
        self.status_updates.append((task_id, status))
        record = self._plans[task_id]
        updated = dataclasses.replace(record, status=status)
        self._plans[task_id] = updated

        return updated


class FakePersistentApprovalService:
    def __init__(self) -> None:
        self.approved: list[PlanReview] = []
        self.rejected: list[PlanReview] = []

    def approve_and_save(self, review: PlanReview) -> ApprovalRecord:
        self.approved.append(review)
        return ApprovalRecord(
            task_id=review.plan.task_id, status="approved"
        )

    def reject_and_save(self, review: PlanReview) -> ApprovalRecord:
        self.rejected.append(review)
        return ApprovalRecord(
            task_id=review.plan.task_id, status="rejected"
        )


class FakePlanExecutionService:
    def __init__(self, result: PlanExecutionResult | None = None) -> None:
        self.executed_task_ids: list[str] = []
        self.result = result or PlanExecutionResult(
            step_results=[
                StepExecutionResult(
                    step_id="coding",
                    status=StepStatus.SUCCESS,
                    output="done",
                )
            ]
        )

    def execute(self, task_id: str) -> PlanExecutionResult:
        self.executed_task_ids.append(task_id)
        return self.result


class FakeTaskCompletionService:
    """completed is explicitly configured, not derived from
    execution_result.succeeded - the CLI wiring test needs to prove it
    obeys TaskCompletionService's domain answer, not that it can
    independently reconstruct the same conclusion from the execution
    result itself."""

    def __init__(self, completed: bool = True) -> None:
        self._completed = completed
        self.calls: list[tuple[str, PlanExecutionResult]] = []

    def complete_if_successful(
        self, task_id: str, execution_result: PlanExecutionResult
    ) -> bool:
        self.calls.append((task_id, execution_result))
        return self._completed


class FakeTaskAgentCleanupService:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def cleanup(self, task_id: str) -> bool:
        self.calls.append(task_id)
        return True


def _plan(task_id: str = "task-001") -> TaskPlan:
    return TaskPlan(
        task_id=task_id,
        steps=[
            TaskStep(
                step_id="coding",
                agent_id="agent-coder",
                description="fix the bug",
            )
        ],
    )


def _wire(
    monkeypatch: pytest.MonkeyPatch,
    plan: TaskPlan,
    execution_result: PlanExecutionResult | None = None,
    completed: bool = True,
):
    plan_service = FakePlanService(plan)
    approval_service = FakePersistentApprovalService()
    execution_service = FakePlanExecutionService(execution_result)
    completion_service = FakeTaskCompletionService(completed)
    cleanup_service = FakeTaskAgentCleanupService()

    monkeypatch.setattr(main, "plan_service", plan_service)
    monkeypatch.setattr(
        main, "persistent_approval_service", approval_service
    )
    monkeypatch.setattr(
        main, "plan_execution_service", execution_service
    )
    monkeypatch.setattr(
        main, "task_completion_service", completion_service
    )
    monkeypatch.setattr(
        main, "task_agent_cleanup_service", cleanup_service
    )

    return (
        plan_service,
        approval_service,
        execution_service,
        completion_service,
        cleanup_service,
    )


def test_plan_command_saves_a_pending_plan_and_does_not_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_service, _, execution_service, _, _ = _wire(
        monkeypatch, _plan()
    )

    main.plan_task("task-001", "fix the bug")

    assert plan_service.create_plan_calls == [
        ("task-001", "fix the bug")
    ]
    record = plan_service.get_plan("task-001")
    assert record is not None
    assert record.status == "pending"
    assert execution_service.executed_task_ids == []


def test_plans_command_lists_pending_plans(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    plan_service, _, _, _, _ = _wire(monkeypatch, _plan())
    plan_service.pending = [
        PlanRecord(
            task_id="task-001", plan=_plan(), created_at="now"
        )
    ]

    main.list_pending_plans()

    output = capsys.readouterr().out
    assert "task-001" in output
    assert "fix the bug" in output
    assert "pending" in output


def test_plans_command_reports_when_nothing_is_pending(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    _wire(monkeypatch, _plan())

    main.list_pending_plans()

    assert "No pending plans." in capsys.readouterr().out


def test_approve_plan_executes_and_marks_the_plan_executed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    (
        plan_service,
        approval_service,
        execution_service,
        completion_service,
        cleanup_service,
    ) = _wire(monkeypatch, _plan())
    main.plan_task("task-001", "fix the bug")

    main.approve_plan("task-001")

    assert len(approval_service.approved) == 1
    assert execution_service.executed_task_ids == ["task-001"]
    assert ("task-001", "approved") in plan_service.status_updates
    assert ("task-001", "executed") in plan_service.status_updates
    assert plan_service.get_plan("task-001").status == "executed"
    assert completion_service.calls == [
        ("task-001", execution_service.result)
    ]


def test_approve_plan_triggers_cleanup_when_task_completes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_service, _, execution_service, completion_service, cleanup_service = (
        _wire(monkeypatch, _plan(), completed=True)
    )
    main.plan_task("task-001", "fix the bug")

    main.approve_plan("task-001")

    assert completion_service.calls == [
        ("task-001", execution_service.result)
    ]
    assert cleanup_service.calls == ["task-001"]
    assert plan_service.get_plan("task-001").status == "executed"


def test_approve_plan_with_no_saved_plan_does_not_execute(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, approval_service, execution_service, completion_service, cleanup_service = _wire(
        monkeypatch, _plan()
    )
    # Deliberately skip plan_task(), so no plan was ever saved.

    main.approve_plan("missing-task")

    assert approval_service.approved == []
    assert execution_service.executed_task_ids == []
    assert completion_service.calls == []
    assert cleanup_service.calls == []


def test_approve_plan_skips_cleanup_when_task_did_not_complete(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    failed_result = PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="coding",
                status=StepStatus.FAILED,
                error="boom",
            )
        ]
    )
    plan_service, _, _, completion_service, cleanup_service = _wire(
        monkeypatch,
        _plan(),
        execution_result=failed_result,
        completed=False,
    )
    main.plan_task("task-001", "fix the bug")

    main.approve_plan("task-001")

    # Deciding success/failure is TaskCompletionService's job, not the
    # CLI's - it must still be called even when execution failed.
    assert completion_service.calls == [("task-001", failed_result)]
    # completion_service said "not completed" -> cleanup must not run.
    assert cleanup_service.calls == []
    # PlanRecord.executed means "execution attempted", not "succeeded" -
    # that stays unconditional regardless of the outcome.
    assert plan_service.get_plan("task-001").status == "executed"


def test_reject_plan_marks_rejected_and_never_executes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan_service, approval_service, execution_service, _, _ = _wire(
        monkeypatch, _plan()
    )
    main.plan_task("task-001", "fix the bug")

    main.reject_plan("task-001")

    assert len(approval_service.rejected) == 1
    assert execution_service.executed_task_ids == []
    assert plan_service.get_plan("task-001").status == "rejected"


def test_reject_plan_with_no_saved_plan_is_a_no_op(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, approval_service, _, _, _ = _wire(monkeypatch, _plan())

    main.reject_plan("missing-task")

    assert approval_service.rejected == []
