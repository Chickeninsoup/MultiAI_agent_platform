from __future__ import annotations

from pathlib import Path
from typing import Any

from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult
from src.services.tools.git_command import run_git_command
from src.services.tools.handlers.read_file_tool import (
    InvalidToolInputError,
)


class GitDiffTool:
    definition = ToolDefinition(
        name="git_diff",
        description=(
            "Show staged or unstaged Git changes in the repository."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "staged": {
                    "type": "boolean",
                    "description": (
                        "When true, show staged changes. "
                        "Defaults to false."
                    ),
                },
            },
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
        parsed_input = self._validate_input(tool_input)
        staged = parsed_input["staged"]

        arguments = [
            "diff",
            "--no-ext-diff",
            "--no-color",
        ]

        if staged:
            arguments.append("--cached")

        result = run_git_command(
            repository_root=repository_root,
            arguments=arguments,
            max_output_chars=max_output_chars,
        )

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.definition.name,
            success=True,
            output=result.output or "No differences.",
            metadata={
                "staged": staged,
                "truncated": result.truncated,
            },
        )

    @staticmethod
    def _validate_input(
        tool_input: dict[str, Any],
    ) -> dict[str, bool]:
        if not isinstance(tool_input, dict):
            raise InvalidToolInputError(
                "Tool input must be an object."
            )

        allowed_keys = {"staged"}
        unexpected_keys = set(tool_input) - allowed_keys

        if unexpected_keys:
            unexpected = ", ".join(sorted(unexpected_keys))
            raise InvalidToolInputError(
                f"Unexpected input fields: {unexpected}"
            )

        staged = tool_input.get("staged", False)

        if not isinstance(staged, bool):
            raise InvalidToolInputError(
                "'staged' must be a boolean."
            )

        return {
            "staged": staged,
        }