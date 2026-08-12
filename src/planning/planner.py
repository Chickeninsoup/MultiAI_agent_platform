from typing import Protocol

from src.task_plan import TaskPlan


class Planner(Protocol):
    """Something that can turn a user request into a TaskPlan.

    Structural, not nominal - RuleBasedPlanner and any future
    ClaudePlanner satisfy this by having a matching create_plan(),
    with no explicit inheritance needed. Lets ManagerAgent depend on
    "a way to plan" instead of a concrete planning strategy.
    """

    def create_plan(self, request: str, task_id: str) -> TaskPlan:
        ...
