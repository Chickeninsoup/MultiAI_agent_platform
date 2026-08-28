from typing import Protocol

from src.planning.task_planning_context import TaskPlanningContext
from src.task_plan import TaskPlan


class Planner(Protocol):
    """Something that can turn a user request into a TaskPlan.

    Structural, not nominal - RuleBasedPlanner and any future
    ClaudePlanner satisfy this by having a matching create_plan(),
    with no explicit inheritance needed. Lets ManagerAgent depend on
    "a way to plan" instead of a concrete planning strategy.

    context is optional (5E-1B) so existing Planners - and existing
    ManagerAgent() call sites that never pass one - keep working
    unchanged; only a Planner that actually wants extra information
    (available agents, constraints) needs to look at it. Migrated
    from PlanningContext to TaskPlanningContext (Phase 1C-3A) since
    Planner is the boundary that should speak in Task-scoped agents,
    not a system-wide agent list - PlanningContext still exists for
    any caller not yet migrated, but Planner no longer accepts it.
    """

    def create_plan(
        self,
        request: str,
        task_id: str,
        context: TaskPlanningContext | None = None,
    ) -> TaskPlan:
        ...
