from __future__ import annotations

from src.agent_handler import AgentHandler
from src.agent_message import AgentMessage


class MessageRouter:
    """Delivers an AgentMessage to the AgentHandler it's addressed to.

    Takes its handlers via constructor injection rather than looking
    them up through AgentRegistry - AgentRegistry answers "what Agents
    exist" (metadata: role/capabilities/tool-policy), this answers
    "who's actually reachable to handle a message right now" (a live
    handler instance). Not tightly coupling the two keeps routing able
    to change independently of discovery later.
    """

    def __init__(self, agents: list[AgentHandler]) -> None:
        self._agents = {
            agent.agent_id: agent for agent in agents
        }

    def send(self, message: AgentMessage) -> str:
        agent = self._agents.get(message.receiver_id)

        if agent is None:
            raise ValueError(
                f"Unknown agent: {message.receiver_id}"
            )

        return agent.handle(message)
