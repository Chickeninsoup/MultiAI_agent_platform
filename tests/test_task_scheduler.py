from __future__ import annotations

import time

from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_dependency_resolver import TaskDependencyResolver
from src.task_plan import TaskPlan, TaskStep
from src.task_scheduler import TaskScheduler


class FakeExecutor:
    def __init__(self) -> None:
        self.calls: list[TaskStep] = []

    def execute_step(self, step: TaskStep, task_id: str) -> str:
        self.calls.append(step)
        return f"{step.step_id}-done"


class SometimesFailingExecutor:
    def __init__(
        self, failing_step_ids: set[str], error: str = "boom"
    ) -> None:
        self._failing_step_ids = failing_step_ids
        self._error = error
        self.calls: list[TaskStep] = []

    def execute_step(self, step: TaskStep, task_id: str) -> str:
        self.calls.append(step)
        if step.step_id in self._failing_step_ids:
            raise RuntimeError(self._error)
        return f"{step.step_id}-done"


class SleepingExecutor:
    def __init__(self, delay: float) -> None:
        self._delay = delay

    def execute_step(self, step: TaskStep, task_id: str) -> str:
        time.sleep(self._delay)
        return step.step_id


def test_run_dispatches_every_step_in_a_single_wave() -> None:
    step_a = TaskStep(
        step_id="a", agent_id="agent-coder", description="do a"
    )
    step_b = TaskStep(
        step_id="b", agent_id="agent-coder", description="do b"
    )
    executor = FakeExecutor()
    scheduler = TaskScheduler(TaskDependencyResolver(), executor)
    plan = TaskPlan(task_id="task-001", steps=[step_a, step_b])

    scheduler.run(plan)

    assert {step.step_id for step in executor.calls} == {"a", "b"}


def test_run_dispatches_dependent_steps_in_separate_waves() -> None:
    step_a = TaskStep(
        step_id="a", agent_id="agent-researcher", description="do a"
    )
    step_b = TaskStep(
        step_id="b",
        agent_id="agent-coder",
        description="do b",
        depends_on=["a"],
    )
    executor = FakeExecutor()
    scheduler = TaskScheduler(TaskDependencyResolver(), executor)
    plan = TaskPlan(task_id="task-001", steps=[step_a, step_b])

    scheduler.run(plan)

    assert executor.calls == [step_a, step_b]


def test_run_preserves_step_order_within_a_wave() -> None:
    step_a = TaskStep(
        step_id="a", agent_id="agent-coder", description="do a"
    )
    step_b = TaskStep(
        step_id="b", agent_id="agent-coder", description="do b"
    )
    executor = FakeExecutor()
    scheduler = TaskScheduler(TaskDependencyResolver(), executor)
    plan = TaskPlan(task_id="task-001", steps=[step_a, step_b])

    results = scheduler.run(plan)

    assert results == [
        StepExecutionResult(
            step_id="a", status=StepStatus.SUCCESS, output="a-done"
        ),
        StepExecutionResult(
            step_id="b", status=StepStatus.SUCCESS, output="b-done"
        ),
    ]


def test_run_merges_results_from_every_wave() -> None:
    step_a = TaskStep(
        step_id="a", agent_id="agent-researcher", description="do a"
    )
    step_b = TaskStep(
        step_id="b",
        agent_id="agent-coder",
        description="do b",
        depends_on=["a"],
    )
    executor = FakeExecutor()
    scheduler = TaskScheduler(TaskDependencyResolver(), executor)
    plan = TaskPlan(task_id="task-001", steps=[step_a, step_b])

    results = scheduler.run(plan)

    assert results == [
        StepExecutionResult(
            step_id="a", status=StepStatus.SUCCESS, output="a-done"
        ),
        StepExecutionResult(
            step_id="b", status=StepStatus.SUCCESS, output="b-done"
        ),
    ]


def test_run_returns_empty_list_for_empty_plan() -> None:
    executor = FakeExecutor()
    scheduler = TaskScheduler(TaskDependencyResolver(), executor)
    plan = TaskPlan(task_id="task-001", steps=[])

    assert scheduler.run(plan) == []
    assert executor.calls == []


def test_run_executes_independent_steps_in_a_wave_concurrently() -> None:
    step_a = TaskStep(
        step_id="a", agent_id="agent-a", description="do a"
    )
    step_b = TaskStep(
        step_id="b", agent_id="agent-b", description="do b"
    )
    executor = SleepingExecutor(delay=0.2)
    scheduler = TaskScheduler(TaskDependencyResolver(), executor)
    plan = TaskPlan(task_id="task-001", steps=[step_a, step_b])

    start = time.monotonic()
    scheduler.run(plan)
    elapsed = time.monotonic() - start

    assert elapsed < 0.35


def test_run_reports_a_failed_step_without_crashing_its_wave() -> None:
    step_a = TaskStep(
        step_id="a", agent_id="agent-a", description="do a"
    )
    step_b = TaskStep(
        step_id="b", agent_id="agent-b", description="do b"
    )
    step_c = TaskStep(
        step_id="c", agent_id="agent-c", description="do c"
    )
    executor = SometimesFailingExecutor(
        failing_step_ids={"b"}, error="LLM timeout"
    )
    scheduler = TaskScheduler(TaskDependencyResolver(), executor)
    plan = TaskPlan(
        task_id="task-001", steps=[step_a, step_b, step_c]
    )

    results = scheduler.run(plan)

    assert results == [
        StepExecutionResult(
            step_id="a", status=StepStatus.SUCCESS, output="a-done"
        ),
        StepExecutionResult(
            step_id="b", status=StepStatus.FAILED, error="LLM timeout"
        ),
        StepExecutionResult(
            step_id="c", status=StepStatus.SUCCESS, output="c-done"
        ),
    ]


def test_run_skips_a_step_whose_dependency_failed() -> None:
    step_a = TaskStep(
        step_id="a", agent_id="agent-researcher", description="do a"
    )
    step_b = TaskStep(
        step_id="b",
        agent_id="agent-coder",
        description="do b",
        depends_on=["a"],
    )
    executor = SometimesFailingExecutor(
        failing_step_ids={"a"}, error="Unknown agent: missing"
    )
    scheduler = TaskScheduler(TaskDependencyResolver(), executor)
    plan = TaskPlan(task_id="task-001", steps=[step_a, step_b])

    results = scheduler.run(plan)

    assert results == [
        StepExecutionResult(
            step_id="a",
            status=StepStatus.FAILED,
            error="Unknown agent: missing",
        ),
        StepExecutionResult(
            step_id="b",
            status=StepStatus.SKIPPED,
            error="dependency 'a' did not succeed",
        ),
    ]
    assert [step.step_id for step in executor.calls] == ["a"]


def test_run_does_not_skip_an_independent_step_when_another_fails() -> (
    None
):
    step_a = TaskStep(
        step_id="a", agent_id="agent-a", description="do a"
    )
    step_b = TaskStep(
        step_id="b", agent_id="agent-b", description="do b"
    )
    executor = SometimesFailingExecutor(
        failing_step_ids={"a"}, error="boom"
    )
    scheduler = TaskScheduler(TaskDependencyResolver(), executor)
    plan = TaskPlan(task_id="task-001", steps=[step_a, step_b])

    results = scheduler.run(plan)

    assert results == [
        StepExecutionResult(
            step_id="a", status=StepStatus.FAILED, error="boom"
        ),
        StepExecutionResult(
            step_id="b", status=StepStatus.SUCCESS, output="b-done"
        ),
    ]


def test_run_propagates_skip_across_multiple_dependency_levels() -> None:
    step_a = TaskStep(
        step_id="a", agent_id="agent-researcher", description="do a"
    )
    step_b = TaskStep(
        step_id="b",
        agent_id="agent-coder",
        description="do b",
        depends_on=["a"],
    )
    step_c = TaskStep(
        step_id="c",
        agent_id="agent-reviewer",
        description="do c",
        depends_on=["b"],
    )
    executor = SometimesFailingExecutor(
        failing_step_ids={"a"}, error="research failed"
    )
    scheduler = TaskScheduler(TaskDependencyResolver(), executor)
    plan = TaskPlan(
        task_id="task-001", steps=[step_a, step_b, step_c]
    )

    results = scheduler.run(plan)

    assert results == [
        StepExecutionResult(
            step_id="a",
            status=StepStatus.FAILED,
            error="research failed",
        ),
        StepExecutionResult(
            step_id="b",
            status=StepStatus.SKIPPED,
            error="dependency 'a' did not succeed",
        ),
        StepExecutionResult(
            step_id="c",
            status=StepStatus.SKIPPED,
            error="dependency 'b' did not succeed",
        ),
    ]
    assert [step.step_id for step in executor.calls] == ["a"]
