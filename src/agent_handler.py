from typing import Protocol

from src.agent_message import AgentMessage


class AgentHandler(Protocol):
    """Something that can receive and respond to an AgentMessage."""

    @property
    def agent_id(self) -> str:
        ...

    def handle(self, message: AgentMessage) -> str:
        ...
