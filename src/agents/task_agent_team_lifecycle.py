from __future__ import annotations

from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle_errors import (
    TaskAgentTeamStateError,
)
from src.agents.task_agent_team_state import TaskAgentTeamState


class TaskAgentTeamLifecycle:
    """Owns the OPEN -> LOCKED -> RELEASED policy for a Task's agent team.

    Deliberately separate from TaskAgentRegistry: Registry only knows
    how to store/query/remove membership, never when those operations
    are allowed - that's a policy question, and policy questions
    belong at the application layer, not baked into storage. Task_ids
    never seen before default to OPEN so nothing needs to explicitly
    initialize state at Task creation time.
    """

    def __init__(self, registry: TaskAgentRegistry) -> None:
        self._registry = registry
        self._states: dict[str, TaskAgentTeamState] = {}

    def state(self, task_id: str) -> TaskAgentTeamState:
        return self._states.get(task_id, TaskAgentTeamState.OPEN)

    def lock(self, task_id: str) -> None:
        current = self.state(task_id)

        if current is TaskAgentTeamState.RELEASED:
            raise TaskAgentTeamStateError(
                f"Cannot lock task {task_id!r}: its team has "
                "already been released"
            )

        self._states[task_id] = TaskAgentTeamState.LOCKED

    def release(self, task_id: str) -> None:
        self._states[task_id] = TaskAgentTeamState.RELEASED
        self._registry.remove_task_agents(task_id)
