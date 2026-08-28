from __future__ import annotations

from src.execution_checkpoint_repository import (
    ExecutionCheckpointRepository,
)
from src.planning.plan_execution_result import PlanExecutionResult
from src.planning.resume_plan_builder import ResumePlanBuilder
from src.task_plan import TaskPlan
from src.task_scheduler import TaskScheduler


class TaskPlanResumeService:
    """Orchestration glue that makes checkpoint -> continued execution
    actually run (5E-5C-8C-3) - loads the checkpoint, builds the
    resume plan, and hands it to the real TaskScheduler. Nothing else.

    Not a new executor: retry, repair, approval, completion, and
    cleanup all stay exactly where they already live. This class only
    connects three things that already exist and were never wired
    together - ExecutionCheckpointRepository, ResumePlanBuilder,
    TaskScheduler - so a checkpoint can turn back into forward
    progress. TaskScheduler itself is untouched and stays completely
    unaware a resume is happening; it just receives an ordinary,
    smaller TaskPlan.

    Deliberately never re-plans: the original TaskPlan is a required
    argument, not derived from a stored request string re-sent to a
    Planner. "Resume" means continue the plan that was already
    running, not generate a new one - regenerating would sever the
    link between what already ran (the checkpoint) and what a fresh
    plan would think needs to run.

    All three dependencies are required constructor arguments, no
    defaults - matching every other execution-policy dependency in
    this chain. Both a missing checkpoint (ExecutionCheckpointRepository.
    load raises FileNotFoundError) and an inconsistent one
    (ResumePlanBuilder raises ValueError) propagate unhandled - no
    checkpoint is not the same as no execution history, and a
    checkpoint/plan mismatch is corrupt state worth surfacing, not
    guessing through.
    """

    def __init__(
        self,
        checkpoint_repository: ExecutionCheckpointRepository,
        resume_plan_builder: ResumePlanBuilder,
        task_scheduler: TaskScheduler,
    ) -> None:
        self._checkpoint_repository = checkpoint_repository
        self._resume_plan_builder = resume_plan_builder
        self._task_scheduler = task_scheduler

    def resume(
        self, task_id: str, plan: TaskPlan
    ) -> PlanExecutionResult:
        checkpoint = self._checkpoint_repository.load(task_id)
        resume_plan = self._resume_plan_builder.build(plan, checkpoint)
        step_results = self._task_scheduler.run(resume_plan)

        return PlanExecutionResult(step_results=step_results)
