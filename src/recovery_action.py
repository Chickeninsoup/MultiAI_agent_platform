from __future__ import annotations

from enum import Enum


class RecoveryAction(Enum):
    """What the system should do next after an ExecutionFailure,
    system-wide - not "can this be retried" (that's RetryDecision,
    from FailureRetryClassifier), but "what happens next regardless"
    (5E-5C-1).

    Deliberately a pure domain value: this enum doesn't execute
    retries, doesn't call PlanRepairLoop, doesn't touch Task status.
    RecoveryPlanner (5E-5C-2) is what maps an ExecutionFailure to one
    of these; whatever consumes a RecoveryAction later (5E-5C-6/7/8)
    is what actually acts on it.

    RETRY - the same step/plan is worth attempting again as-is.

    REPAIR_PLAN - the plan itself was wrong; retrying it unchanged
    won't help, it needs to be regenerated/repaired first.

    REQUEST_APPROVAL - execution cannot proceed without a decision
    only a human can make.

    ABORT - unrecoverable; stop, don't attempt any automated recovery.
    """

    RETRY = "retry"
    REPAIR_PLAN = "repair_plan"
    REQUEST_APPROVAL = "request_approval"
    ABORT = "abort"
