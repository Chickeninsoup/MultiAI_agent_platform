from __future__ import annotations

from src.models import AgentDefinition
from src.repositories import AgentRepository


class AgentRegistry:
    """Discover what Agents exist and describe them.

    Thin on purpose: AgentRepository already knows how to load one
    Agent by id, and how to list them all. This exists as a distinct,
    separately-named entry point because "what Agents are available"
    is a different question from "read this Agent's files" - future
    consumers (a Manager Agent choosing who to assign work to) should
    depend on this, not reach into AgentRepository directly.
    """

    def __init__(self, agent_repository: AgentRepository) -> None:
        self._agent_repository = agent_repository

    def list_agents(self) -> list[AgentDefinition]:
        return self._agent_repository.list_all()

    def get_agent(self, agent_id: str) -> AgentDefinition:
        return self._agent_repository.load(agent_id)
