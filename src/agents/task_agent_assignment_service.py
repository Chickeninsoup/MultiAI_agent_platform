from __future__ import annotations

from src.agent_registry import AgentRegistry
from src.agents.agent_template_errors import AgentTemplateMismatchError
from src.agents.task_agent import TaskAgent
from src.agents.task_agent_assignment_errors import (
    AgentAlreadyAssignedElsewhereError,
    AgentAlreadyAssignedToTaskError,
    AgentNotFoundForAssignmentError,
    TaskAgentTeamLockedError,
    TaskAgentTeamReleasedError,
    TaskNotFoundForAssignmentError,
)
from src.agents.task_agent_registry import TaskAgentRegistry
from src.agents.task_agent_team_lifecycle import TaskAgentTeamLifecycle
from src.agents.task_agent_team_state import TaskAgentTeamState
from src.models import AgentDefinition
from src.repositories import TaskRepository


class TaskAgentAssignmentService:
    """The only sanctioned way to bind a real Agent to a Task.

    UI/CLI/API should never call task_agent_registry.assign_agent()
    directly - that call has no idea whether the task exists, whether
    the agent_id is a real AgentDefinition, whether the requested
    template_id actually matches that AgentDefinition's own
    template_id (5E-4E-1A - the Planner and the Runtime must agree on
    which template an agent_id means), whether the task's team is
    still OPEN for assignment (5E-4B), or whether that agent is
    already spoken for elsewhere. This is the single boundary that
    enforces all of that before ever touching the Registry, so every
    caller gets the same invariants for free instead of reimplementing
    them (or forgetting to).

    Depends on TaskRepository, not TaskService, for the same reason it
    depends on AgentRegistry, not AgentRuntimeFactory: assignment only
    needs "does this task exist," the smallest read that answers that
    - not a service built for running/handling work.
    """

    def __init__(
        self,
        agent_registry: AgentRegistry,
        task_agent_registry: TaskAgentRegistry,
        task_repository: TaskRepository,
        team_lifecycle: TaskAgentTeamLifecycle,
    ) -> None:
        self._agent_registry = agent_registry
        self._task_agent_registry = task_agent_registry
        self._task_repository = task_repository
        self._team_lifecycle = team_lifecycle

    def assign(
        self, task_id: str, agent_id: str, template_id: str
    ) -> TaskAgent:
        self._require_task_exists(task_id)
        self._require_team_open(task_id)
        agent = self._require_agent_exists(agent_id)
        self._require_template_matches(agent, template_id)

        owner = self._task_agent_registry.owner_task_id(agent_id)

        if owner == task_id:
            raise AgentAlreadyAssignedToTaskError(
                f"Agent {agent_id!r} is already assigned to task "
                f"{task_id!r}"
            )

        if owner is not None:
            raise AgentAlreadyAssignedElsewhereError(
                f"Agent {agent_id!r} is already assigned to task "
                f"{owner!r}"
            )

        task_agent = TaskAgent(
            agent_id=agent_id,
            task_id=task_id,
            template_id=template_id,
        )
        self._task_agent_registry.assign_agent(task_agent)

        return task_agent

    def _require_task_exists(self, task_id: str) -> None:
        try:
            self._task_repository.load(task_id)
        except FileNotFoundError as exc:
            raise TaskNotFoundForAssignmentError(
                f"Task {task_id!r} does not exist"
            ) from exc

    def _require_team_open(self, task_id: str) -> None:
        state = self._team_lifecycle.state(task_id)

        if state is TaskAgentTeamState.LOCKED:
            raise TaskAgentTeamLockedError(
                f"Task {task_id!r}'s agent team is locked - it "
                "already has a planning transaction in progress"
            )

        if state is TaskAgentTeamState.RELEASED:
            raise TaskAgentTeamReleasedError(
                f"Task {task_id!r}'s agent team has been released"
            )

    def _require_agent_exists(self, agent_id: str) -> AgentDefinition:
        try:
            return self._agent_registry.get_agent(agent_id)
        except FileNotFoundError as exc:
            raise AgentNotFoundForAssignmentError(
                f"Agent {agent_id!r} does not exist"
            ) from exc

    def _require_template_matches(
        self, agent: AgentDefinition, template_id: str
    ) -> None:
        if agent.template_id != template_id:
            raise AgentTemplateMismatchError(
                f"Agent {agent.id!r} belongs to template "
                f"{agent.template_id!r}, but assignment requested "
                f"template {template_id!r}"
            )
