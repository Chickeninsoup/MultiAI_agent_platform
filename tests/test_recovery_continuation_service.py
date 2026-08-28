from __future__ import annotations

import pytest

from src.execution_failure import ExecutionFailure, FailureCategory
from src.planning.plan_execution_result import PlanExecutionResult
from src.recovery_continuation_errors import RecoveryContinuationError
from src.recovery_continuation_service import RecoveryContinuationService
from src.runtime_approval_request import RuntimeApprovalRequest
from src.task_plan import TaskPlan, TaskStep


class FakeRuntimeApprovalRepository:
    def __init__(
        self, approvals: dict[str, RuntimeApprovalRequest]
    ) -> None:
        self._approvals = approvals

    def load(self, task_id: str) -> RuntimeApprovalRequest:
        if task_id not in self._approvals:
            raise FileNotFoundError(task_id)

        return self._approvals[task_id]


class FakeTaskPlanResumeService:
    def __init__(self, result: PlanExecutionResult) -> None:
        self._result = result
        self.calls: list[tuple[str, TaskPlan]] = []

    def resume(
        self, task_id: str, plan: TaskPlan
    ) -> PlanExecutionResult:
        self.calls.append((task_id, plan))
        return self._result


def _approval(
    task_id: str = "task-a", status: str = "approved"
) -> RuntimeApprovalRequest:
    return RuntimeApprovalRequest(
        approval_id=f"{task_id}-approval-1",
        task_id=task_id,
        plan_id=task_id,
        failure=ExecutionFailure(
            category=FailureCategory.BLOCKED,
            message="permission denied",
            step_id="step-c",
        ),
        status=status,
    )


def _plan(task_id: str = "task-a") -> TaskPlan:
    return TaskPlan(
        task_id=task_id,
        steps=[
            TaskStep(step_id="a", agent_id="agent-a", description="do a")
        ],
    )


def test_approved_approval_calls_resume_service() -> None:
    resume_service = FakeTaskPlanResumeService(PlanExecutionResult([]))
    service = RecoveryContinuationService(
        FakeRuntimeApprovalRepository({"task-a": _approval()}),
        resume_service,
    )

    service.resume_after_approval("task-a", _plan())

    assert len(resume_service.calls) == 1


def test_pending_approval_is_rejected() -> None:
    resume_service = FakeTaskPlanResumeService(PlanExecutionResult([]))
    service = RecoveryContinuationService(
        FakeRuntimeApprovalRepository(
            {"task-a": _approval(status="pending")}
        ),
        resume_service,
    )

    with pytest.raises(RecoveryContinuationError):
        service.resume_after_approval("task-a", _plan())

    assert resume_service.calls == []


def test_rejected_approval_is_rejected() -> None:
    resume_service = FakeTaskPlanResumeService(PlanExecutionResult([]))
    service = RecoveryContinuationService(
        FakeRuntimeApprovalRepository(
            {"task-a": _approval(status="rejected")}
        ),
        resume_service,
    )

    with pytest.raises(RecoveryContinuationError):
        service.resume_after_approval("task-a", _plan())

    assert resume_service.calls == []


def test_missing_approval_propagates() -> None:
    resume_service = FakeTaskPlanResumeService(PlanExecutionResult([]))
    service = RecoveryContinuationService(
        FakeRuntimeApprovalRepository({}), resume_service
    )

    with pytest.raises(FileNotFoundError):
        service.resume_after_approval("task-a", _plan())


def test_resume_result_passes_through_unchanged() -> None:
    result = PlanExecutionResult([])
    resume_service = FakeTaskPlanResumeService(result)
    service = RecoveryContinuationService(
        FakeRuntimeApprovalRepository({"task-a": _approval()}),
        resume_service,
    )

    returned = service.resume_after_approval("task-a", _plan())

    assert returned is result


def test_task_isolation_only_resumes_the_requested_task() -> None:
    resume_service = FakeTaskPlanResumeService(PlanExecutionResult([]))
    service = RecoveryContinuationService(
        FakeRuntimeApprovalRepository(
            {
                "task-a": _approval("task-a", status="approved"),
                "task-b": _approval("task-b", status="pending"),
            }
        ),
        resume_service,
    )

    service.resume_after_approval("task-a", _plan("task-a"))

    with pytest.raises(RecoveryContinuationError):
        service.resume_after_approval("task-b", _plan("task-b"))

    assert resume_service.calls == [("task-a", _plan("task-a"))]
