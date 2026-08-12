from __future__ import annotations

from src.agent_handler import AgentHandler
from src.agent_handlers.llm_agent_handler import LLMAgentHandler
from src.agent_registry import AgentRegistry
from src.run_service import RunService
from src.task_service import TaskService


class AgentRuntimeFactory:
    """Turns every registered Agent into a live AgentHandler.

    MessageRouter needs concrete handler instances, not just Agent
    metadata - this is what bridges AgentRegistry ("what Agents
    exist") to that list. Every Agent is currently LLM-backed, so
    each becomes an LLMAgentHandler sharing the same TaskService/
    RunService; a future non-LLM Agent type (human, workflow) would
    branch on `agent.role` or a dedicated `agent.type` field here
    rather than push that choice onto callers.
    """

    def __init__(
        self,
        agent_registry: AgentRegistry,
        task_service: TaskService,
        run_service: RunService,
    ) -> None:
        self._agent_registry = agent_registry
        self._task_service = task_service
        self._run_service = run_service

    def create_handlers(self) -> list[AgentHandler]:
        return [
            LLMAgentHandler(
                agent.id,
                self._task_service,
                self._run_service,
            )
            for agent in self._agent_registry.list_agents()
        ]
