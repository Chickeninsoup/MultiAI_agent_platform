from __future__ import annotations

import pytest

from src.execution_checkpoint import ExecutionCheckpoint
from src.planning.resume_plan_builder import ResumePlanBuilder
from src.planning.task_plan_resume_service import TaskPlanResumeService
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_plan import TaskPlan, TaskStep


class FakeCheckpointRepository:
    def __init__(
        self, checkpoint: ExecutionCheckpoint | None = None
    ) -> None:
        self._checkpoint = checkpoint
        self.load_calls: list[str] = []

    def load(self, task_id: str) -> ExecutionCheckpoint:
        self.load_calls.append(task_id)

        if self._checkpoint is None:
            raise FileNotFoundError(task_id)

        return self._checkpoint


class FakeResumePlanBuilder:
    def __init__(self, resume_plan: TaskPlan) -> None:
        self._resume_plan = resume_plan
        self.calls: list[tuple[TaskPlan, ExecutionCheckpoint]] = []

    def build(
        self, plan: TaskPlan, checkpoint: ExecutionCheckpoint
    ) -> TaskPlan:
        self.calls.append((plan, checkpoint))
        return self._resume_plan


class FakeTaskScheduler:
    def __init__(
        self, step_results: list[StepExecutionResult]
    ) -> None:
        self._step_results = step_results
        self.run_calls: list[TaskPlan] = []

    def run(self, plan: TaskPlan) -> list[StepExecutionResult]:
        self.run_calls.append(plan)
        return self._step_results


def _plan() -> TaskPlan:
    return TaskPlan(
        task_id="task-a",
        steps=[
            TaskStep(step_id="A", agent_id="agent-a", description="do a"),
            TaskStep(step_id="B", agent_id="agent-b", description="do b"),
            TaskStep(
                step_id="C",
                agent_id="agent-c",
                description="do c",
                depends_on=["A", "B"],
            ),
        ],
    )


def _checkpoint(task_id: str = "task-a") -> ExecutionCheckpoint:
    return ExecutionCheckpoint(
        task_id=task_id,
        plan_id="plan-1",
        completed_step_ids=("A", "B"),
        step_results=(
            StepExecutionResult(step_id="A", status=StepStatus.SUCCESS),
            StepExecutionResult(step_id="B", status=StepStatus.SUCCESS),
        ),
        blocked_step_id="C",
    )


def test_successful_resume_flow_runs_only_remaining_steps() -> None:
    checkpoint_repository = FakeCheckpointRepository(_checkpoint())
    scheduler = FakeTaskScheduler([])
    service = TaskPlanResumeService(
        checkpoint_repository, ResumePlanBuilder(), scheduler
    )

    service.resume("task-a", _plan())

    assert [step.step_id for step in scheduler.run_calls[0].steps] == [
        "C"
    ]


def test_checkpoint_repository_is_used_not_bypassed() -> None:
    checkpoint_repository = FakeCheckpointRepository(_checkpoint())
    scheduler = FakeTaskScheduler([])
    service = TaskPlanResumeService(
        checkpoint_repository, ResumePlanBuilder(), scheduler
    )

    service.resume("task-a", _plan())

    assert checkpoint_repository.load_calls == ["task-a"]


def test_original_plan_and_checkpoint_are_forwarded_to_the_builder() -> (
    None
):
    checkpoint = _checkpoint()
    plan = _plan()
    checkpoint_repository = FakeCheckpointRepository(checkpoint)
    builder = FakeResumePlanBuilder(plan)
    scheduler = FakeTaskScheduler([])
    service = TaskPlanResumeService(
        checkpoint_repository, builder, scheduler
    )

    service.resume("task-a", plan)

    assert builder.calls == [(plan, checkpoint)]


def test_missing_checkpoint_propagates() -> None:
    checkpoint_repository = FakeCheckpointRepository(None)
    scheduler = FakeTaskScheduler([])
    service = TaskPlanResumeService(
        checkpoint_repository, ResumePlanBuilder(), scheduler
    )

    with pytest.raises(FileNotFoundError):
        service.resume("task-a", _plan())


def test_scheduler_results_pass_through_unchanged() -> None:
    step_results = [
        StepExecutionResult(step_id="C", status=StepStatus.SUCCESS)
    ]
    checkpoint_repository = FakeCheckpointRepository(_checkpoint())
    scheduler = FakeTaskScheduler(step_results)
    service = TaskPlanResumeService(
        checkpoint_repository, ResumePlanBuilder(), scheduler
    )

    result = service.resume("task-a", _plan())

    assert result.step_results is step_results


def test_resume_plan_builder_errors_propagate() -> None:
    """A checkpoint/plan mismatch (ResumePlanBuilder raises
    ValueError) must not be swallowed."""

    checkpoint_repository = FakeCheckpointRepository(
        _checkpoint(task_id="task-b")
    )
    scheduler = FakeTaskScheduler([])
    service = TaskPlanResumeService(
        checkpoint_repository, ResumePlanBuilder(), scheduler
    )

    with pytest.raises(ValueError):
        service.resume("task-a", _plan())
