from typing import Protocol

from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult


class ToolHandler(Protocol):
    """A single tool's definition and execution logic."""

    definition: ToolDefinition

    def execute(self, call: ToolCall) -> ToolResult:
        ...


class ToolExecutor(Protocol):
    """Dispatches a tool call to the matching handler."""

    def execute(self, call: ToolCall) -> ToolResult:
        ...
