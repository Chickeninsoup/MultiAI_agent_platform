from __future__ import annotations

import json

from src.agents.task_agent_info import TaskAgentInfo
from src.planning.claude_planner import ClaudePlanner
from src.planning.task_planning_context import TaskPlanningContext


class RecordingProvider:
    def __init__(self, response: str) -> None:
        self._response = response
        self.received_prompt: str | None = None

    def complete(self, prompt: str) -> str:
        self.received_prompt = prompt
        return self._response


def _response(steps: list[dict]) -> str:
    return json.dumps({"steps": steps})


def test_create_plan_uses_the_task_id_and_provider_response() -> None:
    provider = RecordingProvider(
        _response(
            [
                {
                    "step_id": "code",
                    "agent_id": "agent-coder",
                    "description": "implement",
                    "depends_on": [],
                }
            ]
        )
    )
    planner = ClaudePlanner(provider=provider)

    plan = planner.create_plan("implement feature", "task1")

    assert plan.task_id == "task1"
    assert len(plan.steps) == 1
    assert plan.steps[0].agent_id == "agent-coder"
    assert plan.steps[0].step_id == "code"


def test_create_plan_sends_the_request_to_the_provider() -> None:
    provider = RecordingProvider(_response([]))
    planner = ClaudePlanner(provider=provider)

    planner.create_plan("implement feature", "task1")

    assert provider.received_prompt is not None
    assert "implement feature" in provider.received_prompt


def test_create_plan_forwards_context_into_the_prompt() -> None:
    provider = RecordingProvider(_response([]))
    planner = ClaudePlanner(provider=provider)
    context = TaskPlanningContext(
        task_id="task1",
        available_agents=[
            TaskAgentInfo(agent_id="agent-coder", role="Coder")
        ],
    )

    planner.create_plan("implement feature", "task1", context)

    assert "agent-coder" in provider.received_prompt


def test_create_plan_accepts_a_task_planning_context() -> None:
    provider = RecordingProvider(_response([]))
    planner = ClaudePlanner(provider=provider)
    context = TaskPlanningContext(
        task_id="task1",
        available_agents=[
            TaskAgentInfo(agent_id="agent-coder", role="Coder")
        ],
    )

    plan = planner.create_plan("implement feature", "task1", context)

    assert plan.task_id == "task1"


def test_create_plan_preserves_step_dependencies() -> None:
    provider = RecordingProvider(
        _response(
            [
                {
                    "step_id": "research",
                    "agent_id": "agent-researcher",
                    "description": "research",
                    "depends_on": [],
                },
                {
                    "step_id": "coding",
                    "agent_id": "agent-coder",
                    "description": "implement",
                    "depends_on": ["research"],
                },
            ]
        )
    )
    planner = ClaudePlanner(provider=provider)

    plan = planner.create_plan("implement feature", "task1")

    assert plan.steps[1].depends_on == ["research"]


def test_create_plan_returns_empty_steps_for_empty_response() -> None:
    provider = RecordingProvider(_response([]))
    planner = ClaudePlanner(provider=provider)

    plan = planner.create_plan("implement feature", "task1")

    assert plan.steps == []


class RecordingPromptBuilder:
    def __init__(self) -> None:
        self.context: TaskPlanningContext | None = None

    def build(self, request: str, context) -> str:
        self.context = context
        return "prompt"


def test_claude_planner_passes_task_context_to_prompt_builder() -> None:
    prompt_builder = RecordingPromptBuilder()
    planner = ClaudePlanner(
        provider=RecordingProvider(_response([])),
        prompt_builder=prompt_builder,
    )
    context = TaskPlanningContext(task_id="task-1", available_agents=[])

    planner.create_plan("task", "task-1", context)

    assert prompt_builder.context is context


def test_claude_planner_sends_task_scoped_agent_prompt() -> None:
    provider = RecordingProvider(_response([]))
    planner = ClaudePlanner(provider=provider)
    context = TaskPlanningContext(
        task_id="task-a",
        available_agents=[
            TaskAgentInfo(
                agent_id="agent-a", role="Backend Developer"
            )
        ],
    )

    planner.create_plan("build feature", "task-a", context)

    assert "agent-a" in provider.received_prompt
    assert "ONLY agents" in provider.received_prompt
    assert "Do NOT invent agent IDs" in provider.received_prompt
