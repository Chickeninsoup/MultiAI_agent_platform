from __future__ import annotations

from src.planning.plan_validation import PlanValidationResult
from src.planning.validation_error import ValidationError
from src.task_dependency_resolver import (
    CyclicDependencyError,
    TaskDependencyResolver,
)
from src.task_plan import TaskPlan


class PlanValidator:
    """Checks whether a TaskPlan is safe to hand to the Scheduler.

    Sits between Planner and execution (5D-5C): a Planner - rule-based
    today, LLM-backed later - has no guarantee its output is
    executable, so this catches unknown agents, out-of-task agents,
    dangling depends_on, and dependency cycles before anything is
    dispatched. Deliberately stops at producing a PlanValidationResult
    - it doesn't reject, fix, or block a plan itself; wiring that
    decision into the execution flow (auto-reject, or route to Human
    Review) belongs to a later stage, not this validator.

    agent_registry and task_agent_registry check two different things
    on purpose (Phase 1-E): agent_registry answers "does this agent_id
    exist at all" (UNKNOWN_AGENT - Claude hallucinated an id that maps
    to no real, executable agent); task_agent_registry answers "is
    this agent assigned to this specific task" (AGENT_NOT_IN_TASK - a
    real agent, just not one this Task owns). Keeping both matters for
    Repair: the two error codes tell Claude two different things went
    wrong. task_agent_registry is deliberately never asked "does this
    agent exist in some other task" - Validator gets no cross-task
    visibility, only "is it in *this* task's list or not", preserving
    the same isolation TaskAgentRegistry itself enforces structurally.

    Every error this validator currently produces is repairable=True
    (5E-3A) - a wrong agent name, a dangling dependency, or a cycle
    are all things a regenerated plan could fix. There's no
    non-repairable case here yet (an "empty plan" is valid, not an
    error - see test_empty_plan_is_valid); repairable=False exists on
    ValidationError for a future check that's actually structural, not
    something a different plan could ever resolve.
    """

    def __init__(self, agent_registry, task_agent_registry) -> None:
        self._agent_registry = agent_registry
        self._task_agent_registry = task_agent_registry
        self._resolver = TaskDependencyResolver()

    def validate(self, plan: TaskPlan) -> PlanValidationResult:
        errors: list[ValidationError] = []

        unknown_agent_ids = self._unknown_agent_ids(plan)
        errors.extend(
            self._check_unknown_agents(plan, unknown_agent_ids)
        )
        errors.extend(
            self._check_agent_task_membership(plan, unknown_agent_ids)
        )
        errors.extend(self._check_missing_dependencies(plan))

        if not errors:
            errors.extend(self._check_dependency_cycles(plan))

        return PlanValidationResult(valid=not errors, errors=errors)

    def _unknown_agent_ids(self, plan: TaskPlan) -> set[str]:
        known_agent_ids = {
            agent.id for agent in self._agent_registry.list_agents()
        }

        return {
            step.agent_id
            for step in plan.steps
            if step.agent_id not in known_agent_ids
        }

    def _check_unknown_agents(
        self, plan: TaskPlan, unknown_agent_ids: set[str]
    ) -> list[ValidationError]:
        return [
            ValidationError(
                code="UNKNOWN_AGENT",
                message=f"Unknown agent: {step.agent_id}",
                repairable=True,
            )
            for step in plan.steps
            if step.agent_id in unknown_agent_ids
        ]

    def _check_agent_task_membership(
        self, plan: TaskPlan, unknown_agent_ids: set[str]
    ) -> list[ValidationError]:
        task_agent_ids = {
            agent.agent_id
            for agent in self._task_agent_registry.list_agents(
                plan.task_id
            )
        }

        return [
            ValidationError(
                code="AGENT_NOT_IN_TASK",
                message=(
                    f"Agent {step.agent_id} is not assigned to task "
                    f"{plan.task_id}"
                ),
                repairable=True,
            )
            for step in plan.steps
            if step.agent_id not in unknown_agent_ids
            and step.agent_id not in task_agent_ids
        ]

    def _check_missing_dependencies(
        self, plan: TaskPlan
    ) -> list[ValidationError]:
        step_ids = {step.step_id for step in plan.steps}

        return [
            ValidationError(
                code="MISSING_DEPENDENCY",
                message=f"Missing dependency step: {dependency}",
                repairable=True,
            )
            for step in plan.steps
            for dependency in step.depends_on
            if dependency not in step_ids
        ]

    def _check_dependency_cycles(
        self, plan: TaskPlan
    ) -> list[ValidationError]:
        try:
            self._resolver.resolve(plan)
        except CyclicDependencyError:
            return [
                ValidationError(
                    code="DEPENDENCY_CYCLE",
                    message="Task dependency cycle detected",
                    repairable=True,
                )
            ]

        return []
