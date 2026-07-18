from __future__ import annotations

from pathlib import Path
from typing import Any

from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult
from src.services.tools.path_guard import resolve_repository_path


class InvalidToolInputError(Exception):
    error_code = "INVALID_TOOL_INPUT"


class ReadFileTool:
    definition = ToolDefinition(
        name="read_file",
        description=(
            "Read a UTF-8 text file inside the repository. "
            "Optional line ranges are one-based and inclusive."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository-relative file path.",
                },
                "start_line": {
                    "type": "integer",
                    "minimum": 1,
                },
                "end_line": {
                    "type": "integer",
                    "minimum": 1,
                },
            },
            "required": ["path"],
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

        file_path = resolve_repository_path(
            repository_root,
            parsed_input["path"],
        )

        if not file_path.is_file():
            raise InvalidToolInputError(
                f"Path is not a regular file: {parsed_input['path']}"
            )

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError as error:
            raise InvalidToolInputError(
                f"File is not valid UTF-8 text: {parsed_input['path']}"
            ) from error

        lines = content.splitlines()

        start_line = parsed_input.get("start_line")
        if start_line is None:
            start_line = 1

        end_line = parsed_input.get("end_line")
        if end_line is None:
            end_line = len(lines)

        selected_lines = lines[start_line - 1 : end_line]

        numbered_output = "\n".join(
            f"{line_number}: {line}"
            for line_number, line in enumerate(
                selected_lines,
                start=start_line,
            )
        )

        truncated = len(numbered_output) > max_output_chars
        output = numbered_output[:max_output_chars]

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.definition.name,
            success=True,
            output=output,
            metadata={
                "path": parsed_input["path"],
                "start_line": start_line,
                "end_line": min(end_line, len(lines)),
                "total_lines": len(lines),
                "truncated": truncated,
            },
        )

    @staticmethod
    def _validate_input(
        tool_input: dict[str, Any],
    ) -> dict[str, Any]:
        if not isinstance(tool_input, dict):
            raise InvalidToolInputError(
                "Tool input must be an object."
            )

        allowed_keys = {
            "path",
            "start_line",
            "end_line",
        }

        unexpected_keys = set(tool_input) - allowed_keys

        if unexpected_keys:
            unexpected = ", ".join(sorted(unexpected_keys))
            raise InvalidToolInputError(
                f"Unexpected input fields: {unexpected}"
            )

        path = tool_input.get("path")

        if not isinstance(path, str) or not path.strip():
            raise InvalidToolInputError(
                "'path' must be a non-empty string."
            )

        start_line = tool_input.get("start_line")
        end_line = tool_input.get("end_line")

        if start_line is not None:
            if (
                not isinstance(start_line, int)
                or isinstance(start_line, bool)
                or start_line < 1
            ):
                raise InvalidToolInputError(
                    "'start_line' must be a positive integer."
                )

        if end_line is not None:
            if (
                not isinstance(end_line, int)
                or isinstance(end_line, bool)
                or end_line < 1
            ):
                raise InvalidToolInputError(
                    "'end_line' must be a positive integer."
                )

        if (
            start_line is not None
            and end_line is not None
            and end_line < start_line
        ):
            raise InvalidToolInputError(
                "'end_line' must be greater than or equal "
                "to 'start_line'."
            )

        return {
            "path": path,
            "start_line": start_line,
            "end_line": end_line,
        }