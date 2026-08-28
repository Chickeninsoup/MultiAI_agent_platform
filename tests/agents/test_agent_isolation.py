from __future__ import annotations

from src.agents.task_agent import TaskAgent


def test_agents_belong_to_single_task() -> None:
    agent_a = TaskAgent(
        agent_id="a", task_id="task-a", template_id="coder"
    )
    agent_b = TaskAgent(
        agent_id="b", task_id="task-b", template_id="coder"
    )

    assert agent_a.task_id != agent_b.task_id
