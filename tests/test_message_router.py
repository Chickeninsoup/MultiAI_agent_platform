import pytest

from src.agent_message import AgentMessage
from src.agents.task_agent import TaskAgent
from src.agents.task_agent_registry import TaskAgentRegistry
from src.message_router import MessageRouter
from src.message_routing_errors import AgentNotAssignedToTaskError


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


def _message(receiver_id: str, task_id: str = "task-1") -> AgentMessage:
    return AgentMessage(
        sender_id="manager",
        receiver_id=receiver_id,
        task_id=task_id,
        content="hello",
        context={},
    )


def _registry(assignments: dict[str, list[str]]) -> TaskAgentRegistry:
    registry = TaskAgentRegistry()

    for task_id, agent_ids in assignments.items():
        for agent_id in agent_ids:
            registry.assign_agent(
                TaskAgent(
                    agent_id=agent_id,
                    task_id=task_id,
                    template_id="template",
                )
            )

    return registry


def test_send_delivers_to_matching_agent() -> None:
    agent = FakeAgent("agent-a")
    registry = _registry({"task-1": ["agent-a"]})
    router = MessageRouter([agent], registry)

    result = router.send(_message("agent-a"))

    assert result == "received"
    assert agent.received_messages == [_message("agent-a")]


def test_send_raises_for_unknown_agent() -> None:
    # agent-a is assigned to task-1 (membership passes) but no handler
    # for it exists in this router - that's a different failure than
    # authorization.
    registry = _registry({"task-1": ["agent-a"]})
    router = MessageRouter([], registry)

    with pytest.raises(ValueError, match="Unknown agent: agent-a"):
        router.send(_message("agent-a"))


def test_send_routes_to_correct_agent_among_multiple() -> None:
    agent_a = FakeAgent("agent-a", response="from-a")
    agent_b = FakeAgent("agent-b", response="from-b")
    registry = _registry({"task-1": ["agent-a", "agent-b"]})
    router = MessageRouter([agent_a, agent_b], registry)

    result_a = router.send(_message("agent-a"))
    result_b = router.send(_message("agent-b"))

    assert result_a == "from-a"
    assert result_b == "from-b"
    assert len(agent_a.received_messages) == 1
    assert len(agent_b.received_messages) == 1


def test_router_with_no_agents_rejects_everything() -> None:
    registry = _registry({"task-1": ["agent-a"]})
    router = MessageRouter([], registry)

    with pytest.raises(ValueError, match="Unknown agent"):
        router.send(_message("agent-a"))


# --- 5E-4D-3 Routing Guard: dispatch authorization -------------------


def test_cross_task_dispatch_is_rejected_even_with_a_real_handler() -> (
    None
):
    # agent-b genuinely exists and has a handler in this very router,
    # but is assigned to task-b, not task-a - a real, reachable
    # handler is not authorization to dispatch across tasks.
    agent_a = FakeAgent("agent-a")
    agent_b = FakeAgent("agent-b")
    registry = _registry(
        {"task-a": ["agent-a"], "task-b": ["agent-b"]}
    )
    router = MessageRouter([agent_a, agent_b], registry)

    with pytest.raises(AgentNotAssignedToTaskError):
        router.send(_message("agent-b", task_id="task-a"))

    assert agent_b.received_messages == []


def test_agent_with_no_membership_anywhere_is_rejected() -> None:
    agent_c = FakeAgent("agent-c")
    registry = _registry({"task-a": ["agent-a"]})
    router = MessageRouter([agent_c], registry)

    with pytest.raises(AgentNotAssignedToTaskError):
        router.send(_message("agent-c", task_id="task-a"))


def test_released_task_rejects_dispatch_even_with_a_stale_handler() -> (
    None
):
    agent_a = FakeAgent("agent-a")
    registry = _registry({"task-a": ["agent-a"]})
    # The router still holds a handler built before cleanup ran -
    # authorization must not depend on the router ever finding out.
    router = MessageRouter([agent_a], registry)

    registry.remove_task_agents("task-a")

    with pytest.raises(AgentNotAssignedToTaskError):
        router.send(_message("agent-a", task_id="task-a"))

    assert agent_a.received_messages == []
