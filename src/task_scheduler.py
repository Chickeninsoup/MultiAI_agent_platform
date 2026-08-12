from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_dependency_resolver import TaskDependencyResolver
from src.task_plan import TaskPlan, TaskStep
from src.task_plan_executor import TaskPlanExecutor


class TaskScheduler:
    """Runs a TaskPlan wave by wave, respecting depends_on order.

    Knows only Plan -> waves -> Executor - it never touches
    MessageRouter, AgentMessage, or anything below TaskPlanExecutor.
    Steps within a wave are independent by construction (the resolver
    only groups steps whose dependencies are already satisfied by
    earlier waves), so this dispatches a wave's runnable steps to a
    thread pool and waits for all of them; waves themselves still run
    one after another, since a later wave's steps may depend on this
    one's outcomes.

    A step's failure is caught per-step and turned into a failed
    StepExecutionResult rather than raised, so one bad step doesn't
    take down the wave members that succeeded alongside it. Before
    dispatching a wave, each step's depends_on is checked against
    prior results: if any dependency didn't succeed, the step is
    never sent to the executor at all - it's recorded SKIPPED. This
    propagates transitively (a SKIPPED dependency also blocks its
    dependents), since SKIPPED counts as "not SUCCESS" too. Retrying a
    failed step is not this class's job yet.
    """

    def __init__(
        self,
        resolver: TaskDependencyResolver,
        executor: TaskPlanExecutor,
    ) -> None:
        self._resolver = resolver
        self._executor = executor

    def run(self, plan: TaskPlan) -> list[StepExecutionResult]:
        waves = self._resolver.resolve(plan)
        results_by_id: dict[str, StepExecutionResult] = {}
        results: list[StepExecutionResult] = []

        for wave in waves:
            wave_results = self._run_wave(
                wave, plan.task_id, results_by_id
            )
            for result in wave_results:
                results_by_id[result.step_id] = result
            results.extend(wave_results)

        return results

    def _run_wave(
        self,
        wave: list[TaskStep],
        task_id: str,
        results_by_id: dict[str, StepExecutionResult],
    ) -> list[StepExecutionResult]:
        skip_reasons = {
            step.step_id: reason
            for step in wave
            if (reason := self._skip_reason(step, results_by_id))
            is not None
        }
        runnable = [
            step for step in wave if step.step_id not in skip_reasons
        ]

        futures: dict[str, Future[str]] = {}
        if runnable:
            with ThreadPoolExecutor(max_workers=len(runnable)) as pool:
                futures = {
                    step.step_id: pool.submit(
                        self._executor.execute_step, step, task_id
                    )
                    for step in runnable
                }

        return [
            self._to_result(step, futures[step.step_id])
            if step.step_id in futures
            else StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.SKIPPED,
                error=skip_reasons[step.step_id],
            )
            for step in wave
        ]

    def _skip_reason(
        self,
        step: TaskStep,
        results_by_id: dict[str, StepExecutionResult],
    ) -> str | None:
        for dep_id in step.depends_on:
            dep_result = results_by_id[dep_id]
            if dep_result.status != StepStatus.SUCCESS:
                return f"dependency '{dep_id}' did not succeed"

        return None

    def _to_result(
        self, step: TaskStep, future: Future[str]
    ) -> StepExecutionResult:
        try:
            return StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.SUCCESS,
                output=future.result(),
            )
        except Exception as exc:
            return StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.FAILED,
                error=str(exc),
            )
