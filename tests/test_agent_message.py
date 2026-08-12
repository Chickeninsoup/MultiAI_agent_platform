import pytest

from src.agent_message import AgentMessage


def test_creates_message_with_expected_fields() -> None:
    message = AgentMessage(
        sender_id="manager",
        receiver_id="agent-coder",
        task_id="task-001",
        content="Fix authentication bug",
        context={"files": ["auth.py"]},
    )

    assert message.sender_id == "manager"
    assert message.receiver_id == "agent-coder"
    assert message.task_id == "task-001"
    assert message.content == "Fix authentication bug"
    assert message.context == {"files": ["auth.py"]}


def test_supports_empty_context() -> None:
    message = AgentMessage(
        sender_id="agent-coder",
        receiver_id="manager",
        task_id="task-001",
        content="Done.",
        context={},
    )

    assert message.context == {}


def test_message_is_frozen() -> None:
    message = AgentMessage(
        sender_id="manager",
        receiver_id="agent-coder",
        task_id="task-001",
        content="Fix authentication bug",
        context={},
    )

    with pytest.raises(AttributeError):
        message.content = "changed"  # type: ignore[misc]
