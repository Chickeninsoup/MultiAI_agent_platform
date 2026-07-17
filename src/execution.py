from dataclasses import dataclass, field
from typing import Any, Protocol

from src.models import (
    AgentDefinition,
    RunDefinition,
    TaskDefinition,
)


@dataclass(frozen=True)
class RunExecutionContext:
    task: TaskDefinition
    run: RunDefinition
    agent: AgentDefinition
    run_input: str
    agent_system_prompt: str = ""
    task_background: str = ""
    tool_policy: dict[str, Any] = field(default_factory=dict)
    project_snapshot: str = ""


@dataclass(frozen=True)
class RunExecutionResult:
    output: str
    summary: str


class RunExecutor(Protocol):
    """Execute one run using a prepared execution context."""

    def execute(
        self,
        context: RunExecutionContext,
    ) -> RunExecutionResult:
        ...
