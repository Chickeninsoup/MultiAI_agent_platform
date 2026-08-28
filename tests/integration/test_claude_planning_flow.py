from __future__ import annotations

from src.agents.task_agent_info import TaskAgentInfo
from src.manager_agent import ManagerAgent
from src.planning.claude_planner import ClaudePlanner
from src.planning.planner_parser import PlannerResponseParser
from src.planning.planner_prompt import PlannerPromptBuilder
from src.planning.task_planning_context import TaskPlanningContext


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


def test_manager_to_claude_planner_flow() -> None:
    manager = ManagerAgent(
        planner=ClaudePlanner(
            provider=FakeProvider(),
            prompt_builder=PlannerPromptBuilder(),
            parser=PlannerResponseParser(),
        )
    )

    plan = manager.plan("implement feature", "task1")

    assert plan.task_id == "task1"
    assert len(plan.steps) == 1


def test_manager_to_claude_planner_flow_with_context() -> None:
    manager = ManagerAgent(
        planner=ClaudePlanner(
            provider=FakeProvider(),
            prompt_builder=PlannerPromptBuilder(),
            parser=PlannerResponseParser(),
        )
    )
    context = TaskPlanningContext(
        task_id="task1",
        available_agents=[
            TaskAgentInfo(agent_id="agent-coder", role="Coder")
        ],
        constraints=["no destructive changes"],
    )

    plan = manager.plan("implement feature", "task1", context)

    assert plan.task_id == "task1"
    assert plan.steps[0].agent_id == "agent-coder"
