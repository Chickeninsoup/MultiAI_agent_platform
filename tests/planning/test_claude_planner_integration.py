from __future__ import annotations

from src.planning.claude_planner import ClaudePlanner
from src.planning.planner_parser import PlannerResponseParser
from src.planning.planner_prompt import PlannerPromptBuilder


class FakeProvider:
    def complete(self, prompt: str) -> str:
        return """
        {
        "steps":[
            {
            "step_id":"code",
            "agent_id":"agent-coder",
            "description":"implement",
            "depends_on":[]
            }
        ]
        }
        """


def test_claude_planner_creates_task_plan() -> None:
    planner = ClaudePlanner(
        provider=FakeProvider(),
        prompt_builder=PlannerPromptBuilder(),
        parser=PlannerResponseParser(),
    )

    plan = planner.create_plan("implement feature", "task1")

    assert plan.task_id == "task1"
    assert len(plan.steps) == 1
    assert plan.steps[0].agent_id == "agent-coder"
