from __future__ import annotations

from src.execution_failure import ExecutionFailure, FailureCategory
from src.planning.plan_execution_result import PlanExecutionResult
from src.recovery_action import RecoveryAction
from src.recovery_orchestrator import RecoveryOrchestrator
from src.recovery_planner import RecoveryPlanner
from src.step_execution_result import StepExecutionResult, StepStatus


def _orchestrator() -> RecoveryOrchestrator:
    return RecoveryOrchestrator(RecoveryPlanner())


def test_single_failure_produces_a_single_action() -> None:
    failure = ExecutionFailure(
        category=FailureCategory.TEMPORARY_ERROR,
        message="timeout",
        step_id="a",
    )
    result = PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="a", status=StepStatus.FAILED, failure=failure
            )
        ]
    )

    plan = _orchestrator().plan(result)

    assert len(plan.steps) == 1
    assert plan.steps[0].failure == failure
    assert plan.steps[0].action == RecoveryAction.RETRY


def test_multiple_failures_produce_one_action_each() -> None:
    result = PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="a",
                status=StepStatus.SUCCESS,
                output="done",
            ),
            StepExecutionResult(
                step_id="b",
                status=StepStatus.FAILED,
                failure=ExecutionFailure(
                    category=FailureCategory.PLAN_ERROR,
                    message="invalid arguments",
                    step_id="b",
                ),
            ),
            StepExecutionResult(
                step_id="c",
                status=StepStatus.FAILED,
                failure=ExecutionFailure(
                    category=FailureCategory.BLOCKED,
                    message="permission denied",
                    step_id="c",
                ),
            ),
        ]
    )

    plan = _orchestrator().plan(result)

    assert [step.action for step in plan.steps] == [
        RecoveryAction.REPAIR_PLAN,
        RecoveryAction.REQUEST_APPROVAL,
    ]


def test_action_order_matches_step_results_order() -> None:
    result = PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="a",
                status=StepStatus.FAILED,
                failure=ExecutionFailure(
                    category=FailureCategory.FATAL,
                    message="corrupted state",
                    step_id="a",
                ),
            ),
            StepExecutionResult(
                step_id="b",
                status=StepStatus.FAILED,
                failure=ExecutionFailure(
                    category=FailureCategory.TEMPORARY_ERROR,
                    message="timeout",
                    step_id="b",
                ),
            ),
        ]
    )

    plan = _orchestrator().plan(result)

    assert [step.failure.step_id for step in plan.steps] == ["a", "b"]
    assert [step.action for step in plan.steps] == [
        RecoveryAction.ABORT,
        RecoveryAction.RETRY,
    ]


def test_no_failures_produces_an_empty_plan() -> None:
    result = PlanExecutionResult(
        step_results=[
            StepExecutionResult(
                step_id="a", status=StepStatus.SUCCESS, output="done"
            ),
            StepExecutionResult(
                step_id="b", status=StepStatus.SUCCESS, output="done"
            ),
        ]
    )

    plan = _orchestrator().plan(result)

    assert plan.steps == []
