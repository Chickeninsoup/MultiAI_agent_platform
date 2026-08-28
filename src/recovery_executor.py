from __future__ import annotations

from src.planning.failure_repair_request_builder import (
    FailureRepairRequestBuilder,
)
from src.planning.runtime_plan_repair_service import (
    RuntimePlanRepairService,
)
from src.recovery_action import RecoveryAction
from src.recovery_execution_context import RecoveryExecutionContext
from src.recovery_plan import RecoveryPlan, RecoveryStepAction
from src.retry_manager import RetryManager
from src.runtime_approval_service import RuntimeApprovalService


class RecoveryExecutor:
    """Routes a RecoveryPlan's steps to the recovery mechanism their
    RecoveryAction names (5E-5C-6/7C/8D-5) - never re-decides anything
    itself.

    RETRY looks up the originating TaskStep by failure.step_id and
    calls the real RetryManager.execute(step, executor, task_id) - not
    a stand-in, so FailureRetryClassifier (inside RetryManager) still
    gets to veto a retry per-attempt exactly as it does when
    TaskScheduler drives it directly.

    REPAIR_PLAN delegates request construction to
    FailureRepairRequestBuilder and execution to
    RuntimePlanRepairService - this class only decides *which*
    collaborator a step_action's action routes to, never how a
    PlanRepairRequest is shaped (that's the builder's job) or whether
    a failure category warrants repair (that's already been decided,
    by RecoveryPlanner, before this ever runs).

    REQUEST_APPROVAL calls RuntimeApprovalService.create() to persist
    a pending approval - nothing more. This class never approves,
    rejects, or resumes; that lifecycle belongs entirely to
    RuntimeApprovalService (approve/reject) and, later,
    RecoveryContinuationService (resume once approved). plan_id is
    passed as context.task_id (5E-5C-8D-5) - TaskPlan/PlanRecord have
    no separate plan identifier anywhere in this codebase today (one
    plan per task_id, same as everything else here), so plan_id is
    degenerate to task_id for now. The field stays on
    RuntimeApprovalRequest/ExecutionCheckpoint for when multi-plan-
    per-task (replan/repair producing a new plan version) needs to
    distinguish them - not invented here, just not usable yet.

    ABORT is silently skipped for now - that's termination wiring left
    for a later stage, not a decision this class makes.

    retry_manager/runtime_plan_repair_service/
    failure_repair_request_builder/runtime_approval_service are all
    required constructor arguments (no defaults), matching every other
    execution-policy dependency in this chain - omitting any of them
    fails fast at construction, not silently at the first
    REPAIR_PLAN/RETRY/REQUEST_APPROVAL it encounters.
    """

    def __init__(
        self,
        retry_manager: RetryManager,
        runtime_plan_repair_service: RuntimePlanRepairService,
        failure_repair_request_builder: FailureRepairRequestBuilder,
        runtime_approval_service: RuntimeApprovalService,
    ) -> None:
        self._retry_manager = retry_manager
        self._runtime_plan_repair_service = runtime_plan_repair_service
        self._failure_repair_request_builder = (
            failure_repair_request_builder
        )
        self._runtime_approval_service = runtime_approval_service

    def execute(
        self, plan: RecoveryPlan, context: RecoveryExecutionContext
    ) -> None:
        for step_action in plan.steps:
            if step_action.action is RecoveryAction.RETRY:
                self._retry(step_action, context)
            elif step_action.action is RecoveryAction.REPAIR_PLAN:
                self._repair(step_action, context)
            elif step_action.action is RecoveryAction.REQUEST_APPROVAL:
                self._request_approval(step_action, context)

    def _retry(
        self,
        step_action: RecoveryStepAction,
        context: RecoveryExecutionContext,
    ) -> None:
        step_id = step_action.failure.step_id
        if step_id is None:
            return

        step = context.steps_by_id[step_id]
        self._retry_manager.execute(
            step, context.executor, context.task_id
        )

    def _repair(
        self,
        step_action: RecoveryStepAction,
        context: RecoveryExecutionContext,
    ) -> None:
        request = self._failure_repair_request_builder.build(
            context.task_id,
            context.plan,
            step_action.failure,
            context.planning_context,
        )
        self._runtime_plan_repair_service.repair(request)

    def _request_approval(
        self,
        step_action: RecoveryStepAction,
        context: RecoveryExecutionContext,
    ) -> None:
        self._runtime_approval_service.create(
            context.task_id,
            context.task_id,
            step_action.failure,
        )
