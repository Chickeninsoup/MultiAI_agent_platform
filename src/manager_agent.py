from __future__ import annotations

from src.planning.planner import Planner
from src.planning.rule_based_planner import RuleBasedPlanner
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
    """

    def __init__(self, planner: Planner | None = None) -> None:
        self._planner = planner or RuleBasedPlanner()

    def plan(self, request: str, task_id: str) -> TaskPlan:
        return self._planner.create_plan(request, task_id)
