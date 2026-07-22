from typing import Protocol

from src.models import RunExecutionContext, RunExecutionResult


class RunExecutor(Protocol):
    """Execute one run using a prepared execution context."""

    def execute(
        self,
        context: RunExecutionContext,
    ) -> RunExecutionResult:
        ...
