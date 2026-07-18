from __future__ import annotations

from pathlib import Path
from typing import Any

from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult
from src.services.tools.git_command import run_git_command
from src.services.tools.handlers.read_file_tool import (
    InvalidToolInputError,
)


class GitStatusTool:
    definition = ToolDefinition(
        name="git_status",
        description=(
            "Show the current Git branch and working-tree status "
            "for the repository."
        ),
        input_schema={
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    )

    def execute(
        self,
        *,
        tool_call_id: str,
        tool_input: dict[str, Any],
        repository_root: Path,
        max_output_chars: int,
    ) -> ToolResult:
        self._validate_input(tool_input)

        result = run_git_command(
            repository_root=repository_root,
            arguments=[
                "status",
                "--short",
                "--branch",
                "--untracked-files=all",
            ],
            max_output_chars=max_output_chars,
        )

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.definition.name,
            success=True,
            output=result.output or "Working tree clean.",
            metadata={
                "truncated": result.truncated,
            },
        )

    @staticmethod
    def _validate_input(
        tool_input: dict[str, Any],
    ) -> None:
        if not isinstance(tool_input, dict):
            raise InvalidToolInputError(
                "Tool input must be an object."
            )

        if tool_input:
            unexpected = ", ".join(sorted(tool_input))
            raise InvalidToolInputError(
                f"Unexpected input fields: {unexpected}"
            )