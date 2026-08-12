from __future__ import annotations

from src.planning.plan_validation import PlanValidationResult
from src.task_dependency_resolver import (
    CyclicDependencyError,
    TaskDependencyResolver,
)
from src.task_plan import TaskPlan


class PlanValidator:
    """Checks whether a TaskPlan is safe to hand to the Scheduler.

    Sits between Planner and execution (5D-5C): a Planner - rule-based
    today, LLM-backed later - has no guarantee its output is
    executable, so this catches unknown agents, dangling depends_on,
    and dependency cycles before anything is dispatched. Deliberately
    stops at producing a PlanValidationResult - it doesn't reject,
    fix, or block a plan itself; wiring that decision into the
    execution flow (auto-reject, or route to Human Review) belongs to
    a later stage, not this validator.
    """

    def __init__(self, agent_registry) -> None:
        self._agent_registry = agent_registry
        self._resolver = TaskDependencyResolver()

    def validate(self, plan: TaskPlan) -> PlanValidationResult:
        errors: list[str] = []

        errors.extend(self._check_unknown_agents(plan))
        errors.extend(self._check_missing_dependencies(plan))

        if not errors:
            errors.extend(self._check_dependency_cycles(plan))

        return PlanValidationResult(valid=not errors, errors=errors)

    def _check_unknown_agents(self, plan: TaskPlan) -> list[str]:
        known_agent_ids = {
            agent.id for agent in self._agent_registry.list_agents()
        }

        return [
            f"Unknown agent: {step.agent_id}"
            for step in plan.steps
            if step.agent_id not in known_agent_ids
        ]

    def _check_missing_dependencies(self, plan: TaskPlan) -> list[str]:
        step_ids = {step.step_id for step in plan.steps}

        return [
            f"Missing dependency step: {dependency}"
            for step in plan.steps
            for dependency in step.depends_on
            if dependency not in step_ids
        ]

    def _check_dependency_cycles(self, plan: TaskPlan) -> list[str]:
        try:
            self._resolver.resolve(plan)
        except CyclicDependencyError:
            return ["Task dependency cycle detected"]

        return []
