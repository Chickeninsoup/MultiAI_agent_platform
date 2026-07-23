from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult
from src.services.tools.file_writer import (
    atomic_write_text,
    calculate_sha256,
)
from src.services.tools.handlers.read_file_tool import (
    InvalidToolInputError,
)
from src.services.tools.path_guard import resolve_repository_write_path

WriteMode = Literal["create", "overwrite"]

SENSITIVE_FILE_NAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
}

SENSITIVE_DIRECTORY_NAMES = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
}

SENSITIVE_SUFFIXES = {
    ".pem",
    ".key",
}


class WriteFileError(Exception):
    error_code = "WRITE_FILE_FAILED"


class FileAlreadyExistsToolError(WriteFileError):
    error_code = "FILE_ALREADY_EXISTS"


class FileNotFoundToolError(WriteFileError):
    error_code = "FILE_NOT_FOUND"


class SensitivePathToolError(WriteFileError):
    error_code = "SENSITIVE_PATH"


class WriteSizeLimitToolError(WriteFileError):
    error_code = "WRITE_SIZE_LIMIT_EXCEEDED"


@dataclass(frozen=True)
class WriteFileInput:
    path: str
    content: str
    mode: WriteMode


class WriteFileTool:
    definition = ToolDefinition(
        name="write_file",
        description=(
            "Create or overwrite a UTF-8 text file inside the "
            "repository. The tool cannot access paths outside "
            "the repository."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": (
                        "Repository-relative destination path."
                    ),
                },
                "content": {
                    "type": "string",
                    "description": (
                        "Complete UTF-8 text content to write."
                    ),
                },
                "mode": {
                    "type": "string",
                    "enum": [
                        "create",
                        "overwrite",
                    ],
                    "description": (
                        "'create' rejects existing files; "
                        "'overwrite' permits replacing one. "
                        "Defaults to 'create'."
                    ),
                },
            },
            "required": [
                "path",
                "content",
            ],
            "additionalProperties": False,
        },
    )

    def __init__(
        self,
        *,
        max_write_bytes: int = 100_000,
    ) -> None:
        self._max_write_bytes = max_write_bytes

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

        target_path = resolve_repository_write_path(
            repository_root,
            parsed_input.path,
        )

        root = repository_root.expanduser().resolve(strict=True)
        relative_path = target_path.relative_to(root)

        self._validate_sensitive_path(relative_path)

        encoded_content = parsed_input.content.encode("utf-8")

        if len(encoded_content) > self._max_write_bytes:
            raise WriteSizeLimitToolError(
                f"Content exceeds maximum write size of "
                f"{self._max_write_bytes} bytes."
            )

        target_exists = target_path.exists()

        if parsed_input.mode == "create" and target_exists:
            raise FileAlreadyExistsToolError(
                f"File already exists: {parsed_input.path}"
            )

        if parsed_input.mode == "overwrite" and not target_exists:
            raise FileNotFoundToolError(
                f"File does not exist: {parsed_input.path}"
            )

        if target_exists and not target_path.is_file():
            raise InvalidToolInputError(
                f"Path is not a regular file: {parsed_input.path}"
            )

        old_content = (
            target_path.read_text(encoding="utf-8")
            if target_exists
            else None
        )
        before_sha256 = (
            calculate_sha256(old_content)
            if old_content is not None
            else None
        )
        after_sha256 = calculate_sha256(parsed_input.content)

        atomic_write_text(
            target_path=target_path,
            content=parsed_input.content,
        )

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.definition.name,
            success=True,
            output=(
                f"{'Created' if not target_exists else 'Overwrote'} "
                f"{parsed_input.path}"
            ),
            metadata={
                "path": parsed_input.path,
                "mode": parsed_input.mode,
                "created": not target_exists,
                "overwritten": target_exists,
                "bytes_written": len(encoded_content),
                "before_sha256": before_sha256,
                "after_sha256": after_sha256,
            },
        )

    @staticmethod
    def _validate_sensitive_path(relative_path: Path) -> None:
        if SENSITIVE_DIRECTORY_NAMES.intersection(relative_path.parts):
            raise SensitivePathToolError(
                f"Writing to sensitive path is not allowed: "
                f"{relative_path}"
            )

        file_name = relative_path.name

        if (
            file_name in SENSITIVE_FILE_NAMES
            or file_name.startswith(".env.")
            or relative_path.suffix in SENSITIVE_SUFFIXES
        ):
            raise SensitivePathToolError(
                f"Writing to sensitive path is not allowed: "
                f"{relative_path}"
            )

    @staticmethod
    def validate_input(
        tool_input: dict[str, Any],
    ) -> WriteFileInput:
        if not isinstance(tool_input, dict):
            raise InvalidToolInputError(
                "Tool input must be an object."
            )

        allowed_keys = {
            "path",
            "content",
            "mode",
        }
        unexpected_keys = set(tool_input) - allowed_keys

        if unexpected_keys:
            unexpected = ", ".join(sorted(unexpected_keys))
            raise InvalidToolInputError(
                f"Unexpected input fields: {unexpected}"
            )

        path_value = tool_input.get("path")

        if not isinstance(path_value, str) or not path_value.strip():
            raise InvalidToolInputError(
                "'path' must be a non-empty string."
            )

        if "\x00" in path_value:
            raise InvalidToolInputError(
                "'path' must not contain null characters."
            )

        content_value = tool_input.get("content")

        if not isinstance(content_value, str):
            raise InvalidToolInputError(
                "'content' must be a string."
            )

        mode_value = tool_input.get("mode", "create")

        if mode_value not in {"create", "overwrite"}:
            raise InvalidToolInputError(
                "'mode' must be either 'create' or 'overwrite'."
            )

        return WriteFileInput(
            path=path_value,
            content=content_value,
            mode=mode_value,
        )
