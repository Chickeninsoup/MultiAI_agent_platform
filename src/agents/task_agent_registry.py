from __future__ import annotations

from collections import defaultdict

from src.agents.task_agent import TaskAgent


class TaskAgentRegistry:
    """Stores agents within task boundaries.

    Task scoped, not global - lookups are always keyed by task_id
    first, so an agent registered under one task is structurally
    unreachable from another task's queries. Doesn't create Agents
    (that's a future AgentLifecycleManager/UI concern) and doesn't
    know about AgentTemplate (that's user-owned data, this only
    manages the runtime task_id -> TaskAgent binding) - just
    register/query/remove.

    _owners (5E-4A) is a narrow ownership index (agent_id -> the one
    task_id it's currently assigned to), not a cross-task read path -
    it deliberately only answers "is this agent_id already spoken
    for," which is exactly the invariant TaskAgentAssignmentService
    needs to enforce "an agent belongs to at most one task." There is
    still no get_agent_from_any_task() or similar; owner_task_id()
    returns an id, never another task's TaskAgent data.
    """

    def __init__(self) -> None:
        self._agents: dict[str, list[TaskAgent]] = defaultdict(list)
        self._owners: dict[str, str] = {}

    def assign_agent(self, agent: TaskAgent) -> None:
        self._agents[agent.task_id].append(agent)
        self._owners[agent.agent_id] = agent.task_id

    def list_agents(self, task_id: str) -> list[TaskAgent]:
        return list(self._agents.get(task_id, []))

    def get_agent(
        self, task_id: str, agent_id: str
    ) -> TaskAgent | None:
        for agent in self._agents.get(task_id, []):
            if agent.agent_id == agent_id:
                return agent

        return None

    def owner_task_id(self, agent_id: str) -> str | None:
        return self._owners.get(agent_id)

    def remove_task_agents(self, task_id: str) -> None:
        agents = self._agents.pop(task_id, None)

        if agents is None:
            return

        for agent in agents:
            self._owners.pop(agent.agent_id, None)
