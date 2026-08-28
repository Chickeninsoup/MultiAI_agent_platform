from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor

from src.failure_classifier import FailureClassifier
from src.failure_retry_classifier import FailureRetryClassifier
from src.retry_manager import RetryManager
from src.retry_policy import RetryPolicy
from src.step_execution_result import StepExecutionResult, StepStatus
from src.task_dependency_resolver import TaskDependencyResolver
from src.task_plan import TaskPlan, TaskStep
from src.task_plan_executor import TaskPlanExecutor


class _SingleAttemptExecutor:
    """Adapts TaskPlanExecutor's raw (str | raises) contract into the
    StepExecutionResult-returning contract RetryManager expects.

    This is exactly the conversion TaskScheduler always did itself
    (previously named _to_result) - extracted so RetryManager can call
    it once per attempt, without TaskPlanExecutor's own interface
    changing at all.

    failure_classifier is a required constructor argument, not an
    internally-created default (5E-5B-3B) - classification is
    execution policy, and this is the one place a real caught
    Exception becomes an ExecutionFailure, so which FailureClassifier
    is used should be visible at the composition root
    (TaskScheduler's own caller), not hidden inside this adapter.
    """

    def __init__(
        self,
        executor: TaskPlanExecutor,
        failure_classifier: FailureClassifier,
    ) -> None:
        self._executor = executor
        self._failure_classifier = failure_classifier

    def execute_step(
        self, step: TaskStep, task_id: str
    ) -> StepExecutionResult:
        try:
            output = self._executor.execute_step(step, task_id)

            return StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.SUCCESS,
                output=output,
            )
        except Exception as exc:
            failure = self._failure_classifier.classify(
                exc, step.step_id
            )

            return StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.FAILED,
                error=str(exc),
                failure=failure,
            )


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

    Retrying a failed step is RetryManager's job, not this class's -
    Scheduler only decides *when* a step is eligible to run
    (dependencies, wave ordering); it hands each step to RetryManager,
    which may call the (adapted) executor more than once per its
    RetryPolicy, all within that step's own worker thread, without
    Scheduler ever looping itself. Defaults to RetryPolicy() -
    max_attempts=1 - so a TaskScheduler built without an explicit
    retry_manager behaves exactly as it did before retries existed.

    Before dispatching a wave, each step's depends_on is checked
    against prior results: if any dependency didn't succeed, the step
    is never sent to the executor at all - it's recorded SKIPPED. This
    propagates transitively (a SKIPPED dependency also blocks its
    dependents), since SKIPPED counts as "not SUCCESS" too - this
    applies after retries are exhausted, so a step that fails even
    after retrying still blocks its dependents exactly like an
    unretried failure would.

    failure_classifier is required, with no internal default (5E-5B-3B)
    - unlike retry_manager, which safely defaults to "don't retry" if
    omitted, there's no equally safe default classification, so the
    caller must say explicitly which FailureClassifier real failures
    go through.
    """

    def __init__(
        self,
        resolver: TaskDependencyResolver,
        executor: TaskPlanExecutor,
        failure_classifier: FailureClassifier,
        retry_manager: RetryManager | None = None,
    ) -> None:
        self._resolver = resolver
        self._executor = _SingleAttemptExecutor(
            executor, failure_classifier
        )
        self._retry_manager = (
            retry_manager
            if retry_manager is not None
            else RetryManager(RetryPolicy(), FailureRetryClassifier())
        )

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

        futures: dict[str, "Future[StepExecutionResult]"] = {}
        if runnable:
            with ThreadPoolExecutor(max_workers=len(runnable)) as pool:
                futures = {
                    step.step_id: pool.submit(
                        self._execute_with_retry, step, task_id
                    )
                    for step in runnable
                }

        return [
            futures[step.step_id].result()
            if step.step_id in futures
            else StepExecutionResult(
                step_id=step.step_id,
                status=StepStatus.SKIPPED,
                error=skip_reasons[step.step_id],
            )
            for step in wave
        ]

    def _execute_with_retry(
        self, step: TaskStep, task_id: str
    ) -> StepExecutionResult:
        return self._retry_manager.execute(
            step, self._executor, task_id
        ).final_result

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
