from __future__ import annotations

from pathlib import Path
from typing import Any

from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult
from src.services.tools.handlers.read_file_tool import (
    InvalidToolInputError,
)
from src.services.tools.path_guard import resolve_repository_path


class ListFilesTool:
    definition = ToolDefinition(
        name="list_files",
        description=(
            "List files and directories inside the repository. "
            "The path must refer to a directory."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Repository-relative directory path. "
                        "Defaults to '.'."
                    ),
                },
                "recursive": {
                    "type": "boolean",
                    "description": (
                        "Whether to recursively list nested entries."
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

        requested_path = parsed_input["path"]
        recursive = parsed_input["recursive"]

        directory_path = resolve_repository_path(
            repository_root,
            requested_path,
        )

        if not directory_path.is_dir():
            raise InvalidToolInputError(
                f"Path is not a directory: {requested_path}"
            )

        entries = self._collect_entries(
            repository_root=repository_root.resolve(),
            directory_path=directory_path,
            recursive=recursive,
        )

        output_text = "\n".join(entries)
        truncated = len(output_text) > max_output_chars

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.definition.name,
            success=True,
            output=output_text[:max_output_chars],
            metadata={
                "path": requested_path,
                "recursive": recursive,
                "total_entries": len(entries),
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
            "recursive",
        }

        unexpected_keys = set(tool_input) - allowed_keys

        if unexpected_keys:
            unexpected = ", ".join(sorted(unexpected_keys))
            raise InvalidToolInputError(
                f"Unexpected input fields: {unexpected}"
            )

        path_value = tool_input.get("path", ".")

        if not isinstance(path_value, str) or not path_value.strip():
            raise InvalidToolInputError(
                "'path' must be a non-empty string."
            )

        recursive = tool_input.get("recursive", False)

        if not isinstance(recursive, bool):
            raise InvalidToolInputError(
                "'recursive' must be a boolean."
            )

        return {
            "path": path_value,
            "recursive": recursive,
        }

    @classmethod
    def _collect_entries(
        cls,
        *,
        repository_root: Path,
        directory_path: Path,
        recursive: bool,
    ) -> list[str]:
        entries: list[str] = []

        for child in sorted(
            directory_path.iterdir(),
            key=lambda item: item.name,
        ):
            if child.name == ".git":
                continue

            resolved_child = child.resolve()

            if not resolved_child.is_relative_to(repository_root):
                continue

            relative_path = child.relative_to(repository_root)

            if child.is_dir():
                entries.append(f"{relative_path}/")

                if recursive:
                    entries.extend(
                        cls._collect_entries(
                            repository_root=repository_root,
                            directory_path=child,
                            recursive=True,
                        )
                    )
            else:
                entries.append(str(relative_path))

        return entries