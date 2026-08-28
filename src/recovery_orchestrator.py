from __future__ import annotations

from src.planning.plan_execution_result import PlanExecutionResult
from src.recovery_plan import RecoveryPlan, RecoveryStepAction
from src.recovery_planner import RecoveryPlanner


class RecoveryOrchestrator:
    """Turns a PlanExecutionResult's failures into a RecoveryPlan
    (5E-5C-4) - the domain layer PlanRepairLoop/RetryManager/
    ApprovalService will eventually be routed through, not any of
    those things itself.

    Delegates every individual decision to RecoveryPlanner rather than
    re-deriving it - this class owns "pair failures with actions, in
    order," never "what does this FailureCategory mean." No
    FailureRetryClassifier, no RetryManager, no PlanRepairLoop, no
    ApprovalService reference yet: those are 5E-5C-6/7/8's job once
    something actually consumes a RecoveryPlan.

    recovery_planner is a required constructor argument, not an
    internally-created default, matching every other execution-policy
    dependency in this chain (FailureClassifier on
    _SingleAttemptExecutor, FailureRetryClassifier on RetryManager).
    """

    def __init__(self, recovery_planner: RecoveryPlanner) -> None:
        self._recovery_planner = recovery_planner

    def plan(self, result: PlanExecutionResult) -> RecoveryPlan:
        return RecoveryPlan(
            steps=[
                RecoveryStepAction(
                    failure=failure,
                    action=self._recovery_planner.decide(failure),
                )
                for failure in result.failures
            ]
        )
