from __future__ import annotations

from src.planning.planner import Planner
from src.planning.rule_based_planner import RuleBasedPlanner
from src.planning.task_planning_context import TaskPlanningContext
from src.task_plan import TaskPlan


class ManagerAgent:
    """Turns a user request into a TaskPlan other Agents can act on.

    Coordinates planning rather than doing it: plan() delegates to an
    injected Planner (5D-5A) so how a request becomes a TaskPlan -
    fixed single-step today, LLM-backed later - can change without
    touching Manager. Defaults to RuleBasedPlanner so every existing
    ManagerAgent() call site keeps its current fixed-plan behavior
    unchanged. Manager only plans; converting a TaskPlan into
    AgentMessages and actually routing them is a separate concern
    (TaskPlanConverter + whatever executes the plan), so plan() stops
    at TaskPlan. task_id is caller-supplied rather than generated
    here, matching how every other entry point in this codebase (e.g.
    TaskService.create_task_and_run) takes an explicit task_id instead
    of inventing one internally.

    plan() always forwards context through to the Planner, even when
    it's None (5E-1B) - every Planner's create_plan() declares that
    parameter with its own default, so this never needs to branch on
    whether the caller supplied one. context is typed as
    TaskPlanningContext (Phase 1C-3A) rather than PlanningContext -
    Manager itself doesn't build one (that's TaskPlanningContextFactory's
    job, assembled by whatever application layer calls plan()), it
    only forwards whatever it's handed.
    """

    def __init__(self, planner: Planner | None = None) -> None:
        self._planner = planner or RuleBasedPlanner()

    def plan(
        self,
        request: str,
        task_id: str,
        context: TaskPlanningContext | None = None,
    ) -> TaskPlan:
        # TODO(Phase 1C, task-id consistency): task_id and
        # context.task_id can disagree (e.g. context built for a
        # different task) - deliberately not validated here. Manager
        # only transports context; that check belongs at whatever
        # boundary builds/validates TaskPlanningContext (Context
        # Factory / a future validation layer), not here.
        return self._planner.create_plan(request, task_id, context)
