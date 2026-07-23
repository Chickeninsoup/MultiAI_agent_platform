from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult
from src.services.tools.file_writer import (
    atomic_write_text,
    calculate_sha256,
)
from src.services.tools.handlers.read_file_tool import (
    InvalidToolInputError,
)
from src.services.tools.path_guard import (
    resolve_repository_write_path,
)


class PatchFileError(Exception):
    """Base error for patch_file."""


class PatchFileNotFoundError(PatchFileError):
    """Target file does not exist."""

    error_code = "PATCH_FILE_NOT_FOUND"


class PatchMatchNotFoundError(PatchFileError):
    """old_text does not exist."""

    error_code = "PATCH_MATCH_NOT_FOUND"


class PatchAmbiguousMatchError(PatchFileError):
    """old_text matched multiple locations."""

    error_code = "PATCH_AMBIGUOUS_MATCH"


@dataclass(frozen=True)
class PatchFileInput:
    path: str
    old_text: str
    new_text: str


class PatchFileTool:
    definition = ToolDefinition(
        name="patch_file",
        description=(
            "Replace an exact, unique block of text inside a "
            "UTF-8 text file in the repository. Fails if the "
            "text does not appear, or appears more than once."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Repository-relative file path."
                    ),
                },
                "old_text": {
                    "type": "string",
                    "description": (
                        "Exact existing text to replace."
                    ),
                },
                "new_text": {
                    "type": "string",
                    "description": (
                        "Replacement text."
                    ),
                },
            },
            "required": [
                "path",
                "old_text",
                "new_text",
            ],
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
        del max_output_chars

        parsed_input = self.validate_input(tool_input)

        metadata = self.apply_patch(
            repository_root=repository_root,
            path=parsed_input.path,
            old_text=parsed_input.old_text,
            new_text=parsed_input.new_text,
        )

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.definition.name,
            success=True,
            output=f"Patched {parsed_input.path}",
            metadata=metadata,
        )

    @staticmethod
    def validate_input(
        tool_input: dict[str, Any],
    ) -> PatchFileInput:
        if not isinstance(tool_input, dict):
            raise InvalidToolInputError(
                "Tool input must be an object."
            )

        allowed_keys = {
            "path",
            "old_text",
            "new_text",
        }

        unexpected_keys = (
            set(tool_input)
            - allowed_keys
        )

        if unexpected_keys:
            unexpected = ", ".join(
                sorted(unexpected_keys)
            )

            raise InvalidToolInputError(
                f"Unexpected input fields: {unexpected}"
            )

        path_value = tool_input.get("path")

        if (
            not isinstance(path_value, str)
            or not path_value.strip()
        ):
            raise InvalidToolInputError(
                "'path' must be a non-empty string."
            )

        if "\x00" in path_value:
            raise InvalidToolInputError(
                "'path' must not contain null characters."
            )

        old_text_value = tool_input.get(
            "old_text"
        )

        if (
            not isinstance(old_text_value, str)
            or not old_text_value
        ):
            raise InvalidToolInputError(
                "'old_text' must be a non-empty string."
            )

        new_text_value = tool_input.get(
            "new_text"
        )

        if not isinstance(new_text_value, str):
            raise InvalidToolInputError(
                "'new_text' must be a string."
            )

        return PatchFileInput(
            path=path_value,
            old_text=old_text_value,
            new_text=new_text_value,
        )

    @staticmethod
    def find_patch_location(
        content: str,
        old_text: str,
    ) -> int:
        match_count = content.count(old_text)

        if match_count == 0:
            raise PatchMatchNotFoundError(
                "old_text was not found."
            )

        if match_count > 1:
            raise PatchAmbiguousMatchError(
                "old_text matched multiple locations."
            )

        return content.index(old_text)

    @staticmethod
    def load_target_content(target_path: Path) -> str:
        if not target_path.exists():
            raise PatchFileNotFoundError(
                f"File does not exist: {target_path}"
            )

        if not target_path.is_file():
            raise PatchFileNotFoundError(
                f"Target is not a file: {target_path}"
            )

        return target_path.read_text(encoding="utf-8")

    @staticmethod
    def preview_patch(
        *,
        repository_root: Path,
        path: str,
        old_text: str,
        new_text: str,
    ) -> dict[str, object]:
        target_path = resolve_repository_write_path(
            repository_root,
            path,
        )

        content = PatchFileTool.load_target_content(target_path)

        index = PatchFileTool.find_patch_location(
            content,
            old_text,
        )

        updated_content = (
            content[:index]
            + new_text
            + content[index + len(old_text) :]
        )

        return {
            "path": path,
            "match_index": index,
            "old_length": len(old_text),
            "new_length": len(new_text),
            "updated_content": updated_content,
        }

    @staticmethod
    def apply_patch(
        *,
        repository_root: Path,
        path: str,
        old_text: str,
        new_text: str,
    ) -> dict[str, object]:
        target_path = resolve_repository_write_path(
            repository_root,
            path,
        )

        content = PatchFileTool.load_target_content(target_path)

        index = PatchFileTool.find_patch_location(
            content,
            old_text,
        )

        updated_content = (
            content[:index]
            + new_text
            + content[index + len(old_text) :]
        )

        before_sha256 = calculate_sha256(content)
        after_sha256 = calculate_sha256(updated_content)

        atomic_write_text(
            target_path=target_path,
            content=updated_content,
        )

        return {
            "operation": "patch",
            "path": path,
            "before_sha256": before_sha256,
            "after_sha256": after_sha256,
            "bytes_written": len(
                updated_content.encode("utf-8")
            ),
        }
