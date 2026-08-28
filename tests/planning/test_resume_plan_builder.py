from __future__ import annotations

import pytest

from src.execution_checkpoint import ExecutionCheckpoint
from src.planning.resume_plan_builder import ResumePlanBuilder
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_dependency_resolver import TaskDependencyResolver
from src.task_plan import TaskPlan, TaskStep


def _plan() -> TaskPlan:
    return TaskPlan(
        task_id="task-1",
        steps=[
            TaskStep(step_id="A", agent_id="agent-a", description="do a"),
            TaskStep(step_id="B", agent_id="agent-b", description="do b"),
            TaskStep(
                step_id="C",
                agent_id="agent-c",
                description="do c",
                depends_on=["A", "B"],
            ),
            TaskStep(
                step_id="D",
                agent_id="agent-d",
                description="do d",
                depends_on=["C"],
            ),
        ],
    )


def _success(step_id: str) -> StepExecutionResult:
    return StepExecutionResult(step_id=step_id, status=StepStatus.SUCCESS)


def _checkpoint(
    completed_step_ids: tuple[str, ...],
    blocked_step_id: str | None = None,
    task_id: str = "task-1",
) -> ExecutionCheckpoint:
    return ExecutionCheckpoint(
        task_id=task_id,
        plan_id="plan-1",
        completed_step_ids=completed_step_ids,
        step_results=tuple(
            _success(step_id) for step_id in completed_step_ids
        ),
        blocked_step_id=blocked_step_id,
    )


def test_removes_completed_steps() -> None:
    resume_plan = ResumePlanBuilder().build(
        _plan(), _checkpoint(("A", "B"), blocked_step_id="C")
    )

    assert [step.step_id for step in resume_plan.steps] == ["C", "D"]


def test_rewrites_dependencies_to_drop_completed_step_ids() -> None:
    resume_plan = ResumePlanBuilder().build(
        _plan(), _checkpoint(("A", "B"), blocked_step_id="C")
    )

    step_c = next(s for s in resume_plan.steps if s.step_id == "C")
    assert step_c.depends_on == []


def test_keeps_dependencies_on_remaining_steps() -> None:
    resume_plan = ResumePlanBuilder().build(
        _plan(), _checkpoint(("A", "B"), blocked_step_id="C")
    )

    step_d = next(s for s in resume_plan.steps if s.step_id == "D")
    assert step_d.depends_on == ["C"]


def test_preserves_step_order() -> None:
    resume_plan = ResumePlanBuilder().build(
        _plan(), _checkpoint(("A",))
    )

    assert [step.step_id for step in resume_plan.steps] == ["B", "C", "D"]


def test_rejects_checkpoint_referencing_a_step_not_in_the_plan() -> None:
    with pytest.raises(ValueError):
        ResumePlanBuilder().build(_plan(), _checkpoint(("X",)))


def test_rejects_checkpoint_for_a_different_task() -> None:
    with pytest.raises(ValueError):
        ResumePlanBuilder().build(
            _plan(), _checkpoint(("A",), task_id="task-2")
        )


def test_rejects_a_blocked_step_that_is_also_marked_completed() -> None:
    with pytest.raises(ValueError):
        ResumePlanBuilder().build(
            _plan(), _checkpoint(("A", "B", "C"), blocked_step_id="C")
        )


def test_resume_plan_keeps_the_original_task_id() -> None:
    resume_plan = ResumePlanBuilder().build(
        _plan(), _checkpoint(("A", "B"), blocked_step_id="C")
    )

    assert resume_plan.task_id == "task-1"


def test_resume_plan_resolves_cleanly_without_a_false_cycle() -> None:
    """The 5E-5C-8C-1 audit's core finding: a naive filter (dropping
    completed TaskSteps without rewriting depends_on) makes
    TaskDependencyResolver misreport a legitimate resume as a
    dependency cycle, since it has no memory of a previous run. This
    proves the real resolver accepts ResumePlanBuilder's output."""

    resume_plan = ResumePlanBuilder().build(
        _plan(), _checkpoint(("A", "B"), blocked_step_id="C")
    )

    waves = TaskDependencyResolver().resolve(resume_plan)

    assert [
        [step.step_id for step in wave] for wave in waves
    ] == [["C"], ["D"]]
