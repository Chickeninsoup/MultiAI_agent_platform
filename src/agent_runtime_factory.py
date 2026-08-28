from __future__ import annotations

from src.agent_handler import AgentHandler
from src.agent_handlers.llm_agent_handler import LLMAgentHandler
from src.agent_registry import AgentRegistry
from src.agents.task_agent_registry import TaskAgentRegistry
from src.run_service import RunService
from src.task_service import TaskService


class AgentRuntimeFactory:
    """Turns a Task's assigned TaskAgents into live AgentHandlers.

    Task-scoped (5E-4D-2), not global: create_handlers(task_id) only
    builds handlers for agent_ids TaskAgentRegistry says are assigned
    to that specific task, instead of every AgentDefinition that
    exists anywhere. This is the first execution-side enforcement of
    Task isolation - previously this built a handler for every
    registered Agent regardless of which Task (if any) it was
    assigned to, so MessageRouter could route to any Agent in the
    system.

    Still resolves through AgentRegistry (not just trusting
    TaskAgent.agent_id blindly) - a TaskAgent's agent_id must be a
    real, existing AgentDefinition.id (the identity invariant:
    TaskAgent.agent_id == AgentDefinition.id == TaskStep.agent_id ==
    AgentMessage.receiver_id), never resolved via template_id. Every
    Agent is currently LLM-backed, so each becomes an LLMAgentHandler
    sharing the same TaskService/RunService; a future non-LLM Agent
    type (human, workflow) would branch on `agent.role` or a
    dedicated `agent.type` field here rather than push that choice
    onto callers.
    """

    def __init__(
        self,
        agent_registry: AgentRegistry,
        task_agent_registry: TaskAgentRegistry,
        task_service: TaskService,
        run_service: RunService,
    ) -> None:
        self._agent_registry = agent_registry
        self._task_agent_registry = task_agent_registry
        self._task_service = task_service
        self._run_service = run_service

    def create_handlers(self, task_id: str) -> list[AgentHandler]:
        handlers: list[AgentHandler] = []

        for task_agent in self._task_agent_registry.list_agents(
            task_id
        ):
            agent_definition = self._agent_registry.get_agent(
                task_agent.agent_id
            )

            handlers.append(
                LLMAgentHandler(
                    agent_definition.id,
                    self._task_service,
                    self._run_service,
                )
            )

        return handlers
