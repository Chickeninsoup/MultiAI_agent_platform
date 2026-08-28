from __future__ import annotations

from src.execution_failure import ExecutionFailure, FailureCategory
from src.recovery_action import RecoveryAction


class RecoveryPlanner:
    """Maps an ExecutionFailure's category to system-wide intent
    (5E-5C-2) - "what should happen next," not "should this be
    retried" (that's FailureRetryClassifier.should_retry, a sibling
    decision this deliberately does not call or depend on).

    Decision only: never retries, never calls PlanRepairLoop, never
    requests approval, never touches Task status. Whatever consumes a
    RecoveryAction (5E-5C-6/7/8) is what actually acts on it.

    Unlike FailureClassifier (Exception -> ExecutionFailure), which
    defaults an unrecognized exception to FATAL because a raw
    exception at runtime must always resolve to *something* safe, an
    unrecognized FailureCategory here means this planner's mapping
    itself is incomplete - a coverage gap in code, not a runtime
    surprise. That should fail loudly (ValueError) rather than
    silently default to ABORT, so a new FailureCategory added later
    can't slip through unmapped.
    """

    def decide(self, failure: ExecutionFailure) -> RecoveryAction:
        if failure.category is FailureCategory.TEMPORARY_ERROR:
            return RecoveryAction.RETRY

        if failure.category is FailureCategory.PLAN_ERROR:
            return RecoveryAction.REPAIR_PLAN

        if failure.category is FailureCategory.BLOCKED:
            return RecoveryAction.REQUEST_APPROVAL

        if failure.category is FailureCategory.FATAL:
            return RecoveryAction.ABORT

        raise ValueError(
            f"No RecoveryAction mapped for FailureCategory "
            f"{failure.category!r}"
        )
