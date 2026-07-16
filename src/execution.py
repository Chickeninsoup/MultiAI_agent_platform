from dataclasses import dataclass
from typing import Protocol

from src.models import AgentDefinition, RunDefinition, TaskDefinition


@dataclass(frozen=True)
class RunExecutionContext:
    task: TaskDefinition
    run: RunDefinition
    agent: AgentDefinition
    run_input: str


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
