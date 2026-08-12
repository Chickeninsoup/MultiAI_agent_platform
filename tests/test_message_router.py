import pytest

from src.agent_message import AgentMessage
from src.message_router import MessageRouter


class FakeAgent:
    def __init__(self, agent_id: str, response: str = "received") -> None:
        self._agent_id = agent_id
        self._response = response
        self.received_messages: list[AgentMessage] = []

    @property
    def agent_id(self) -> str:
        return self._agent_id

    def handle(self, message: AgentMessage) -> str:
        self.received_messages.append(message)
        return self._response


def _message(receiver_id: str) -> AgentMessage:
    return AgentMessage(
        sender_id="manager",
        receiver_id=receiver_id,
        task_id="task-1",
        content="hello",
        context={},
    )


def test_send_delivers_to_matching_agent() -> None:
    agent = FakeAgent("agent-a")
    router = MessageRouter([agent])

    result = router.send(_message("agent-a"))

    assert result == "received"
    assert agent.received_messages == [_message("agent-a")]


def test_send_raises_for_unknown_agent() -> None:
    router = MessageRouter([FakeAgent("agent-a")])

    with pytest.raises(ValueError, match="Unknown agent: missing"):
        router.send(_message("missing"))


def test_send_routes_to_correct_agent_among_multiple() -> None:
    agent_a = FakeAgent("agent-a", response="from-a")
    agent_b = FakeAgent("agent-b", response="from-b")
    router = MessageRouter([agent_a, agent_b])

    result_a = router.send(_message("agent-a"))
    result_b = router.send(_message("agent-b"))

    assert result_a == "from-a"
    assert result_b == "from-b"
    assert len(agent_a.received_messages) == 1
    assert len(agent_b.received_messages) == 1


def test_router_with_no_agents_rejects_everything() -> None:
    router = MessageRouter([])

    with pytest.raises(ValueError, match="Unknown agent"):
        router.send(_message("agent-a"))
