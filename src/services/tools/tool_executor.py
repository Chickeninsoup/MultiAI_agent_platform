from __future__ import annotations

import time
from dataclasses import replace
from pathlib import Path
from typing import Protocol

from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult

from src.services.tools.tool_policy import ToolPolicy

class ToolHandler(Protocol):
    definition: ToolDefinition

    def execute(
        self,
        *,
        tool_call_id: str,
        tool_input: dict,
        repository_root: Path,
        max_output_chars: int,
    ) -> ToolResult:
        ...


class ToolExecutor:
    def __init__(
        self,
        *,
        repository_root: Path,
        handlers: list[ToolHandler],
        tool_policy: ToolPolicy,
        max_output_chars: int = 100_000,
    ) -> None:
        self._repository_root = repository_root
        self._tool_policy = tool_policy
        self._max_output_chars = max_output_chars
        self._handlers: dict[str, ToolHandler] = {}

        for handler in handlers:
            tool_name = handler.definition.name

            if tool_name in self._handlers:
                raise ValueError(
                    f"Duplicate tool registration: {tool_name}"
                )

            self._handlers[tool_name] = handler

    def get_definitions(self) -> list[ToolDefinition]:
        return [
            handler.definition
            for name, handler in self._handlers.items()
            if self._tool_policy.is_enabled(name)
        ]


    
    def execute(self, tool_call: ToolCall) -> ToolResult:
        start = time.perf_counter()
        result = self._execute(tool_call)
        duration_ms = round((time.perf_counter() - start) * 1000)

        return replace(
            result,
            metadata={
                **result.metadata,
                "duration_ms": duration_ms,
            },
        )

    def _execute(self, tool_call: ToolCall) -> ToolResult:
        handler = self._handlers.get(tool_call.name)

        if handler is None:
            return self._failure_result(
                tool_call=tool_call,
                error_code="UNKNOWN_TOOL",
                message=f"Unknown tool: {tool_call.name}",
            )

        if not self._tool_policy.is_enabled(tool_call.name):
            return self._failure_result(
                tool_call=tool_call,
                error_code="TOOL_DISABLED",
                message=(
                    f"Tool is disabled by policy: "
                    f"{tool_call.name}"
                ),
            )

        try:
            return handler.execute(
                tool_call_id=tool_call.id,
                tool_input=tool_call.input,
                repository_root=self._repository_root,
                max_output_chars=(
                    self._tool_policy.get_max_output_chars(
                        tool_call.name,
                        self._max_output_chars,
                    )
                ),
            )
        except Exception as error:
            error_code = getattr(
                error,
                "error_code",
                "TOOL_EXECUTION_FAILED",
            )

            return self._failure_result(
                tool_call=tool_call,
                error_code=error_code,
                message=str(error) or error.__class__.__name__,
            )

    @staticmethod
    def _failure_result(
        *,
        tool_call: ToolCall,
        error_code: str,
        message: str,
    ) -> ToolResult:
        return ToolResult(
            tool_call_id=tool_call.id,
            tool_name=tool_call.name,
            success=False,
            output=message,
            error_code=error_code,
        )