from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TaskAgentInfo:
    """The Planner-facing view of a TaskAgent.

    Deliberately narrower than TaskAgent: a Planner needs to know who
    it can assign work to and what they can do, not runtime status,
    task_id, or which template an instance came from - those are
    TaskAgentRegistry/lifecycle concerns, not planning concerns.
    """

    agent_id: str
    role: str
    description: str = ""
    capabilities: list[str] = field(default_factory=list)
