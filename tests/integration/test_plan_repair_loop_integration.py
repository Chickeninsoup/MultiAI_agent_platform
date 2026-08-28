from __future__ import annotations

from src.agents.agent_template import AgentTemplate
from src.agents.agent_template_repository import (
    AgentTemplateRepository,
)
from src.agents.task_agent import TaskAgent
from src.agents.task_agent_registry import TaskAgentRegistry
from src.planning.claude_planner import ClaudePlanner
from src.planning.plan_repair_loop import PlanRepairLoop
from src.planning.plan_validator import PlanValidator
from src.planning.repair_decision_service import RepairDecisionService
from src.planning.repair_planner import RepairPlanner
from src.planning.repair_preparation_service import (
    RepairPreparationService,
)
from src.planning.repair_request_builder import RepairRequestBuilder
from src.planning.task_planning_context_factory import (
    TaskPlanningContextFactory,
)


class FakeAgent:
    def __init__(self, agent_id: str) -> None:
        self.id = agent_id


class FakeAgentRegistry:
    def __init__(self, agent_ids: list[str]) -> None:
        self._agents = [FakeAgent(agent_id) for agent_id in agent_ids]

    def list_agents(self) -> list[FakeAgent]:
        return self._agents


class FakeTaskAgent:
    def __init__(self, agent_id: str) -> None:
        self.agent_id = agent_id


class FakeTaskAgentRegistry:
    def __init__(self, agent_ids: list[str]) -> None:
        self._agents = [FakeTaskAgent(agent_id) for agent_id in agent_ids]

    def list_agents(self, task_id: str) -> list[FakeTaskAgent]:
        return self._agents


class SequenceProvider:
    def __init__(self, responses: list[str]) -> None:
        self._responses = list(responses)
        self.calls = 0
        self.prompts: list[str] = []

    def complete(self, prompt: str) -> str:
        self.prompts.append(prompt)
        response = self._responses[self.calls]
        self.calls += 1
        return response


_INVALID_RESPONSE = """
{
"steps":[
    {
    "step_id":"code",
    "agent_id":"agent-python",
    "description":"implement",
    "depends_on":[]
    }
]
}
"""

_REPAIRED_RESPONSE = """
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


def test_repair_loop_recovers_from_an_unknown_agent() -> None:
    provider = SequenceProvider([_INVALID_RESPONSE, _REPAIRED_RESPONSE])
    planner = ClaudePlanner(provider=provider)
    repair_planner = RepairPlanner(provider=provider)
    validator = PlanValidator(
        FakeAgentRegistry(["agent-coder"]),
        FakeTaskAgentRegistry(["agent-coder"]),
    )
    preparation_service = RepairPreparationService(
        decision_service=RepairDecisionService(),
        builder=RepairRequestBuilder(),
    )
    loop = PlanRepairLoop(
        planner, repair_planner, validator, preparation_service
    )

    result = loop.run("implement feature", "task1")

    assert result.attempts == 2
    assert result.repaired is True
    assert result.plan.steps[0].agent_id == "agent-coder"
    assert provider.calls == 2


_CROSS_TASK_RESPONSE = """
{
"steps":[
    {
    "step_id":"code",
    "agent_id":"agent-b",
    "description":"implement",
    "depends_on":[]
    }
]
}
"""

_CORRECTED_RESPONSE = """
{
"steps":[
    {
    "step_id":"code",
    "agent_id":"agent-a",
    "description":"implement",
    "depends_on":[]
    }
]
}
"""


def test_repair_loop_recovers_from_a_cross_task_agent() -> None:
    """Claude hallucinates a real-but-wrong-task agent (agent-b, which
    belongs to task-b) while planning for task-a; PlanValidator catches
    it as AGENT_NOT_IN_TASK; the repair prompt must only ever offer
    task-a's own agent (agent-a); Claude corrects itself."""

    task_agent_registry = TaskAgentRegistry()
    templates = AgentTemplateRepository()
    templates.save(
        AgentTemplate(template_id="backend", name="Backend Developer")
    )
    task_agent_registry.assign_agent(
        TaskAgent(
            agent_id="agent-a", task_id="task-a", template_id="backend"
        )
    )
    task_agent_registry.assign_agent(
        TaskAgent(
            agent_id="agent-b", task_id="task-b", template_id="backend"
        )
    )
    context_factory = TaskPlanningContextFactory(
        task_agent_registry, templates
    )
    context = context_factory.create("task-a")

    provider = SequenceProvider(
        [_CROSS_TASK_RESPONSE, _CORRECTED_RESPONSE]
    )
    planner = ClaudePlanner(provider=provider)
    repair_planner = RepairPlanner(provider=provider)
    validator = PlanValidator(
        FakeAgentRegistry(["agent-a", "agent-b"]), task_agent_registry
    )
    preparation_service = RepairPreparationService(
        decision_service=RepairDecisionService(),
        builder=RepairRequestBuilder(),
    )
    loop = PlanRepairLoop(
        planner, repair_planner, validator, preparation_service
    )

    result = loop.run("implement backend feature", "task-a", context)

    assert result.attempts == 2
    assert result.repaired is True
    assert result.plan.steps[0].agent_id == "agent-a"

    repair_prompt = provider.prompts[1]
    assert "Agent ID: agent-a" in repair_prompt
    assert "Agent ID: agent-b" not in repair_prompt
