from __future__ import annotations

from src.agents.task_agent_info import TaskAgentInfo
from src.planning.planner_prompt import PlannerPromptBuilder
from src.planning.task_planning_context import TaskPlanningContext


def test_prompt_contains_request() -> None:
    prompt = PlannerPromptBuilder().build("build authentication", None)

    assert "build authentication" in prompt


def test_prompt_contains_agents() -> None:
    context = TaskPlanningContext(
        task_id="task-1",
        available_agents=[
            TaskAgentInfo(agent_id="agent-coder", role="Coder")
        ],
    )

    prompt = PlannerPromptBuilder().build("task", context)

    assert "agent-coder" in prompt


def test_prompt_contains_constraints() -> None:
    context = TaskPlanningContext(
        task_id="task-1",
        available_agents=[],
        constraints=["no destructive changes"],
    )

    prompt = PlannerPromptBuilder().build("task", context)

    assert "no destructive changes" in prompt


def test_prompt_with_no_context_omits_agent_and_constraint_sections() -> (
    None
):
    prompt = PlannerPromptBuilder().build("task", None)

    assert "AVAILABLE AGENTS FOR THIS TASK" not in prompt
    assert "Constraints" not in prompt


def test_prompt_contains_task_agent_metadata() -> None:
    context = TaskPlanningContext(
        task_id="task-1",
        available_agents=[
            TaskAgentInfo(
                agent_id="agent-backend",
                role="Backend Developer",
                description="Builds APIs",
                capabilities=["Python", "API development"],
            )
        ],
    )

    prompt = PlannerPromptBuilder().build("Build login", context)

    assert "agent-backend" in prompt
    assert "Backend Developer" in prompt
    assert "Builds APIs" in prompt
    assert "Python" in prompt
    assert "API development" in prompt


def test_prompt_explicitly_restricts_agent_selection() -> None:
    context = TaskPlanningContext(
        task_id="task-1",
        available_agents=[
            TaskAgentInfo(agent_id="agent-coder", role="Coder")
        ],
    )

    prompt = PlannerPromptBuilder().build("task", context)

    assert "ONLY agents" in prompt
    assert "Do NOT create new agents" in prompt
    assert "Do NOT invent agent IDs" in prompt
    assert "Do NOT reference agents that are not listed" in prompt


def test_prompt_explicitly_handles_no_task_agents() -> None:
    context = TaskPlanningContext(task_id="task-1", available_agents=[])

    prompt = PlannerPromptBuilder().build("Do something", context)

    assert "No agents are currently assigned" in prompt
    assert "Do NOT create" in prompt


def test_prompt_renders_every_assigned_agent() -> None:
    context = TaskPlanningContext(
        task_id="task-1",
        available_agents=[
            TaskAgentInfo(agent_id="agent-backend", role="Backend"),
            TaskAgentInfo(agent_id="agent-reviewer", role="Reviewer"),
        ],
    )

    prompt = PlannerPromptBuilder().build("task", context)

    assert "agent-backend" in prompt
    assert "agent-reviewer" in prompt
    assert "agent-coder" not in prompt
