from __future__ import annotations

import dataclasses

from src.execution_checkpoint import ExecutionCheckpoint
from src.task_plan import TaskPlan


class ResumePlanBuilder:
    """Turns an original TaskPlan + its ExecutionCheckpoint into a
    smaller, dependency-consistent resume TaskPlan (5E-5C-8C-2).

    Pure plan transformation - never runs a step, never calls an
    agent, never touches TaskDependencyResolver/TaskScheduler, never
    saves a checkpoint. TaskScheduler stays exactly as ignorant of
    checkpoints/recovery/approval as it was before this class existed;
    it just receives a smaller, ordinary TaskPlan.

    Not a blind filter (5E-5C-8C-1 audit finding): completed steps are
    dropped from the plan, but every *remaining* step also has its
    depends_on rewritten to drop references to those same completed
    step_ids. TaskDependencyResolver has no memory of a previous run -
    if a remaining step still listed a completed-but-now-absent
    step_id as a dependency, that dependency could never resolve
    within this new, smaller plan, misreporting a legitimate resume as
    a CyclicDependencyError. TaskStep is frozen, so this means
    reconstructing each remaining step via dataclasses.replace, not
    mutating depends_on in place.

    Fails fast (ValueError) rather than silently on any
    checkpoint/plan inconsistency - a mismatched task_id, a completed
    step_id that isn't even in the plan, or a blocked_step_id that's
    also marked completed all mean the checkpoint and plan disagree
    about what happened, which is corrupt state worth surfacing, not
    guessing through.
    """

    def build(
        self, plan: TaskPlan, checkpoint: ExecutionCheckpoint
    ) -> TaskPlan:
        if checkpoint.task_id != plan.task_id:
            raise ValueError(
                f"Checkpoint belongs to task {checkpoint.task_id!r}, "
                f"not plan's task {plan.task_id!r}"
            )

        completed = set(checkpoint.completed_step_ids)
        plan_step_ids = {step.step_id for step in plan.steps}
        missing = completed - plan_step_ids

        if missing:
            raise ValueError(
                "Checkpoint references step_ids not present in the "
                f"plan: {sorted(missing)}"
            )

        if (
            checkpoint.blocked_step_id is not None
            and checkpoint.blocked_step_id in completed
        ):
            raise ValueError(
                f"blocked_step_id {checkpoint.blocked_step_id!r} is "
                "also marked completed - checkpoint is inconsistent"
            )

        remaining_steps = [
            dataclasses.replace(
                step,
                depends_on=[
                    dep_id
                    for dep_id in step.depends_on
                    if dep_id not in completed
                ],
            )
            for step in plan.steps
            if step.step_id not in completed
        ]

        return TaskPlan(task_id=plan.task_id, steps=remaining_steps)
