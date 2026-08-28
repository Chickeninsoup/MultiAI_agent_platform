from __future__ import annotations

from src.agent_handler import AgentHandler
from src.agent_message import AgentMessage
from src.agents.task_agent_registry import TaskAgentRegistry
from src.message_routing_errors import AgentNotAssignedToTaskError


class MessageRouter:
    """Delivers an AgentMessage to the AgentHandler it's addressed to.

    Takes its handlers via constructor injection rather than looking
    them up through AgentRegistry - AgentRegistry answers "what Agents
    exist" (metadata: role/capabilities/tool-policy), this answers
    "who's actually reachable to handle a message right now" (a live
    handler instance). Not tightly coupling the two keeps routing able
    to change independently of discovery later.

    send() is the actual dispatch boundary (5E-4D-3) - the second
    execution-side defense layer, after AgentRuntimeFactory's
    task-scoped handler construction (5E-4D-2). Checks
    TaskAgentRegistry membership against message.task_id *before*
    resolving a handler, and deliberately doesn't stop there: even a
    handler this router happens to hold for message.receiver_id must
    not be dispatched to if that agent isn't currently assigned to
    message.task_id - a stale/leftover handler is not authorization.
    Membership and handler-existence are two different invariants
    (assigned-but-unreachable is a runtime configuration problem, not
    an authorization one), so they raise two different errors and are
    checked in that fixed order: authorization first, then dispatch.
    """

    def __init__(
        self,
        agents: list[AgentHandler],
        task_agent_registry: TaskAgentRegistry,
    ) -> None:
        self._agents = {
            agent.agent_id: agent for agent in agents
        }
        self._task_agent_registry = task_agent_registry

    def send(self, message: AgentMessage) -> str:
        assigned_agent_ids = {
            task_agent.agent_id
            for task_agent in self._task_agent_registry.list_agents(
                message.task_id
            )
        }

        if message.receiver_id not in assigned_agent_ids:
            raise AgentNotAssignedToTaskError(
                f"Agent {message.receiver_id} is not assigned to "
                f"task {message.task_id}"
            )

        agent = self._agents.get(message.receiver_id)

        if agent is None:
            raise ValueError(
                f"Unknown agent: {message.receiver_id}"
            )

        return agent.handle(message)
