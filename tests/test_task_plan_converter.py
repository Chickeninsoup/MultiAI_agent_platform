from __future__ import annotations

from src.agent_message import AgentMessage
from src.task_plan import TaskPlan, TaskStep
from src.task_plan_converter import TaskPlanConverter


def test_to_messages_converts_a_single_step() -> None:
    plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id="agent-coder",
                description="implement login",
            )
        ],
    )

    messages = TaskPlanConverter().to_messages(plan)

    assert messages == [
        AgentMessage(
            sender_id="agent-manager",
            receiver_id="agent-coder",
            task_id="task-001",
            content="implement login",
            context={},
        )
    ]


def test_to_messages_converts_multiple_steps_in_order() -> None:
    plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id="agent-researcher",
                description="find useful APIs",
            ),
            TaskStep(
                step_id="step-2",
                agent_id="agent-coder",
                description="implement scraper",
            ),
        ],
    )

    messages = TaskPlanConverter().to_messages(plan)

    assert [message.receiver_id for message in messages] == [
        "agent-researcher",
        "agent-coder",
    ]
    assert [message.content for message in messages] == [
        "find useful APIs",
        "implement scraper",
    ]
    assert all(message.task_id == "task-001" for message in messages)


def test_to_messages_returns_empty_list_for_empty_plan() -> None:
    plan = TaskPlan(task_id="task-001", steps=[])

    assert TaskPlanConverter().to_messages(plan) == []


def test_to_messages_ignores_depends_on_for_now() -> None:
    plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id="agent-researcher",
                description="find useful APIs",
            ),
            TaskStep(
                step_id="step-2",
                agent_id="agent-coder",
                description="implement scraper",
                depends_on=["step-1"],
            ),
        ],
    )

    messages = TaskPlanConverter().to_messages(plan)

    assert [message.content for message in messages] == [
        "find useful APIs",
        "implement scraper",
    ]


def test_step_to_message_converts_a_single_step() -> None:
    step = TaskStep(
        step_id="step-1",
        agent_id="agent-coder",
        description="implement login",
    )

    message = TaskPlanConverter().step_to_message(step, "task-001")

    assert message == AgentMessage(
        sender_id="agent-manager",
        receiver_id="agent-coder",
        task_id="task-001",
        content="implement login",
        context={},
    )


def test_to_messages_uses_custom_sender_id() -> None:
    plan = TaskPlan(
        task_id="task-001",
        steps=[
            TaskStep(
                step_id="step-1",
                agent_id="agent-coder",
                description="implement login",
            )
        ],
    )

    messages = TaskPlanConverter(sender_id="agent-manager-2").to_messages(
        plan
    )

    assert messages[0].sender_id == "agent-manager-2"
