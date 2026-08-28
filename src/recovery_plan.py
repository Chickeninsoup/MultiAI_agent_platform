from __future__ import annotations

from dataclasses import dataclass

from src.execution_failure import ExecutionFailure
from src.recovery_action import RecoveryAction


@dataclass(frozen=True)
class RecoveryStepAction:
    """One failure's RecoveryAction, paired with the ExecutionFailure
    it was decided from (5E-5C-6).

    Carrying the failure alongside the action - not just the action
    alone - is what lets a RecoveryAction.RETRY be traced back to
    failure.step_id, which is what RecoveryExecutor needs to look up
    the real TaskStep and call RetryManager.execute(step, executor,
    task_id) for real, instead of a bare enum value with nothing to
    act on.
    """

    failure: ExecutionFailure
    action: RecoveryAction


@dataclass(frozen=True)
class RecoveryPlan:
    """Every failure in one PlanExecutionResult, paired with its
    RecoveryAction, in step_results order.

    A list, not a single RecoveryAction, because a Plan can fail in
    more than one way at once - a TEMPORARY_ERROR step alongside a
    PLAN_ERROR step needs both RETRY and REPAIR_PLAN represented, not
    collapsed into one verdict. Pure data: nothing here executes a
    retry, calls PlanRepairLoop, or requests approval - that's
    whatever consumes a RecoveryPlan (RecoveryExecutor, 5E-5C-6+).
    """

    steps: list[RecoveryStepAction]
