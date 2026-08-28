from __future__ import annotations

from src.agents.task_agent_cleanup_errors import (
    TaskNotFoundForCleanupError,
)
from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.repositories import TaskRepository


class TaskAgentCleanupService:
    """Releases a Task's agent team once the Task itself is completed.

    Checks TaskDefinition.status itself rather than trusting the
    caller (5E-4C-3) - defense in depth: TaskCompletionService owns
    "when is a Task allowed to become completed," this owns "only a
    completed Task may have its agents released." A caller that got
    the ordering wrong (e.g. cleaning up right after an execution
    attempt, without checking whether it actually succeeded) still
    can't destroy a running Task's team through this service.
    Deliberately narrow so far: only releases TaskAgent membership/
    ownership/team state - AgentDefinition and AgentTemplate have
    their own physical lifecycle, not touched here.
    """

    def __init__(
        self,
        task_repository: TaskRepository,
        task_agent_registry: TaskAgentRegistry,
        team_lifecycle: TaskAgentTeamLifecycle,
    ) -> None:
        self._task_repository = task_repository
        self._task_agent_registry = task_agent_registry
        self._team_lifecycle = team_lifecycle

    def cleanup(self, task_id: str) -> bool:
        try:
            task = self._task_repository.load(task_id)
        except FileNotFoundError as exc:
            raise TaskNotFoundForCleanupError(
                f"Task not found for cleanup: {task_id}"
            ) from exc

        if task.status != "completed":
            return False

        self._team_lifecycle.release(task_id)

        return True
