from __future__ import annotations

from dataclasses import dataclass

from src.step_execution_result import StepExecutionResult


@dataclass(frozen=True)
class ExecutionCheckpoint:
    """A snapshot of one TaskPlan's execution progress (5E-5C-8A-2) -
    the durability layer confirmed missing by the 5E-5C-8A-1 audit.
    Nothing today persists which steps of a multi-step TaskPlan have
    already run; this is the first model that can.

    task_id scopes the checkpoint to its owning Task - the same
    tasks/<task_id>/ tree PlanRepository/ApprovalRepository/
    TaskRepository already use (5E-5C-8B). plan_id exists separately
    from task_id because a Task can have more than one Plan over its
    lifetime (replan, repair) - a checkpoint belongs to one specific
    Plan attempt, not just "whatever Task this is."

    Deliberately not RunDefinition-shaped and not a TaskDefinition
    field: RunDefinition tracks one Agent execution attempt (a single
    TaskStep's dispatch), TaskDefinition tracks the user-facing Task
    lifecycle - neither is the right granularity for "which steps of
    this multi-step TaskPlan have completed." This is a distinct
    concept at a distinct granularity, not a reuse of either.

    Tuples, not lists - a checkpoint is a snapshot at a point in time,
    not a live buffer something keeps appending to. completed_step_ids
    and step_results are separate fields even though completed_step_ids
    is derivable from step_results (5E-5C-8-adjacent precedent:
    PlanExecutionResult.failures is derived from step_results too) -
    kept explicit here because "which step_ids are done" is what a
    resume executor (5E-5C-8C) checks on every step, while step_results
    is carried for audit/display, not for that check.

    blocked_step_id names the resume entry point: None means every
    step so far either succeeded or was never reached by anything
    requiring a pause (a plain snapshot, not a blocked one). Deliberately
    no status/approval_id/resume_count yet (5E-5C-8A-2 scope) - there is
    no checkpoint lifecycle to encode a status for, no Approval model
    wired to it yet, and resume counting is a metrics concern for
    whichever stage actually implements resuming.
    """

    task_id: str
    plan_id: str
    completed_step_ids: tuple[str, ...]
    step_results: tuple[StepExecutionResult, ...]
    blocked_step_id: str | None
