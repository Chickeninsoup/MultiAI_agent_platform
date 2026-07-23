import hashlib
from pathlib import Path

import pytest

from src.services.tools.handlers.read_file_tool import (
    InvalidToolInputError,
)
from src.services.tools.handlers.write_file_tool import (
    FileAlreadyExistsToolError,
    FileNotFoundToolError,
    SensitivePathToolError,
    WriteFileInput,
    WriteFileTool,
    WriteSizeLimitToolError,
)
from src.services.tools.path_guard import (
    PathNotFoundError,
    PathSecurityError,
)


def test_definition_uses_safe_schema() -> None:
    definition = WriteFileTool.definition

    assert definition.name == "write_file"
    assert definition.input_schema["required"] == [
        "path",
        "content",
    ]
    assert definition.input_schema["additionalProperties"] is False


def test_validates_create_input() -> None:
    result = WriteFileTool.validate_input(
        {
            "path": "src/example.py",
            "content": "print('hello')\n",
            "mode": "create",
        }
    )

    assert result == WriteFileInput(
        path="src/example.py",
        content="print('hello')\n",
        mode="create",
    )


def test_defaults_to_create_mode() -> None:
    result = WriteFileTool.validate_input(
        {
            "path": "README.md",
            "content": "# Project\n",
        }
    )

    assert result.mode == "create"


def test_accepts_overwrite_mode() -> None:
    result = WriteFileTool.validate_input(
        {
            "path": "README.md",
            "content": "# Updated\n",
            "mode": "overwrite",
        }
    )

    assert result.mode == "overwrite"


def test_accepts_empty_content() -> None:
    result = WriteFileTool.validate_input(
        {
            "path": "empty.txt",
            "content": "",
        }
    )

    assert result.content == ""


@pytest.mark.parametrize(
    "tool_input",
    [
        None,
        [],
        "invalid",
        123,
    ],
)
def test_rejects_non_object_input(tool_input: object) -> None:
    with pytest.raises(InvalidToolInputError):
        WriteFileTool.validate_input(tool_input)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "path_value",
    [
        None,
        "",
        "   ",
        123,
        True,
    ],
)
def test_rejects_invalid_path(path_value: object) -> None:
    with pytest.raises(InvalidToolInputError):
        WriteFileTool.validate_input(
            {
                "path": path_value,
                "content": "hello",
            }
        )


def test_rejects_null_character_in_path() -> None:
    with pytest.raises(InvalidToolInputError):
        WriteFileTool.validate_input(
            {
                "path": "src/\x00example.py",
                "content": "hello",
            }
        )


@pytest.mark.parametrize(
    "content_value",
    [
        None,
        123,
        True,
        [],
        {},
    ],
)
def test_rejects_non_string_content(content_value: object) -> None:
    with pytest.raises(InvalidToolInputError):
        WriteFileTool.validate_input(
            {
                "path": "example.txt",
                "content": content_value,
            }
        )


@pytest.mark.parametrize(
    "mode_value",
    [
        "append",
        "delete",
        "",
        123,
        True,
        None,
    ],
)
def test_rejects_invalid_mode(mode_value: object) -> None:
    with pytest.raises(InvalidToolInputError):
        WriteFileTool.validate_input(
            {
                "path": "example.txt",
                "content": "hello",
                "mode": mode_value,
            }
        )


def test_rejects_unexpected_fields() -> None:
    with pytest.raises(InvalidToolInputError):
        WriteFileTool.validate_input(
            {
                "path": "example.txt",
                "content": "hello",
                "shell_command": "rm -rf .",
            }
        )


def test_execute_validates_input_before_touching_disk(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    tool = WriteFileTool()

    with pytest.raises(InvalidToolInputError):
        tool.execute(
            tool_call_id="tool-call-1",
            tool_input={"content": "hello"},
            repository_root=repository_root,
            max_output_chars=1000,
        )


def test_create_writes_new_file(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    tool = WriteFileTool()

    result = tool.execute(
        tool_call_id="tool-call-1",
        tool_input={
            "path": "example.txt",
            "content": "hello\n",
        },
        repository_root=repository_root,
        max_output_chars=1000,
    )

    assert result.success is True
    assert result.metadata["created"] is True
    assert result.metadata["overwritten"] is False
    assert (
        repository_root / "example.txt"
    ).read_text(encoding="utf-8") == "hello\n"

    assert result.metadata["before_sha256"] is None
    assert result.metadata["after_sha256"] == hashlib.sha256(
        "hello\n".encode("utf-8")
    ).hexdigest()


def test_create_writes_empty_file(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    tool = WriteFileTool()

    tool.execute(
        tool_call_id="tool-call-1",
        tool_input={
            "path": "empty.txt",
            "content": "",
        },
        repository_root=repository_root,
        max_output_chars=1000,
    )

    assert (repository_root / "empty.txt").read_text(
        encoding="utf-8"
    ) == ""


def test_create_rejects_existing_file(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "example.txt").write_text(
        "original", encoding="utf-8"
    )

    tool = WriteFileTool()

    with pytest.raises(FileAlreadyExistsToolError):
        tool.execute(
            tool_call_id="tool-call-1",
            tool_input={
                "path": "example.txt",
                "content": "new",
            },
            repository_root=repository_root,
            max_output_chars=1000,
        )

    assert (repository_root / "example.txt").read_text(
        encoding="utf-8"
    ) == "original"


def test_overwrite_replaces_existing_file(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / "example.txt").write_text(
        "original", encoding="utf-8"
    )

    tool = WriteFileTool()

    result = tool.execute(
        tool_call_id="tool-call-1",
        tool_input={
            "path": "example.txt",
            "content": "updated",
            "mode": "overwrite",
        },
        repository_root=repository_root,
        max_output_chars=1000,
    )

    assert result.metadata["created"] is False
    assert result.metadata["overwritten"] is True
    assert (repository_root / "example.txt").read_text(
        encoding="utf-8"
    ) == "updated"

    assert result.metadata["before_sha256"] == hashlib.sha256(
        "original".encode("utf-8")
    ).hexdigest()
    assert result.metadata["after_sha256"] == hashlib.sha256(
        "updated".encode("utf-8")
    ).hexdigest()
    assert (
        result.metadata["before_sha256"]
        != result.metadata["after_sha256"]
    )


def test_overwrite_rejects_missing_file(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    tool = WriteFileTool()

    with pytest.raises(FileNotFoundToolError):
        tool.execute(
            tool_call_id="tool-call-1",
            tool_input={
                "path": "missing.txt",
                "content": "updated",
                "mode": "overwrite",
            },
            repository_root=repository_root,
            max_output_chars=1000,
        )


def test_rejects_missing_parent_directory(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    tool = WriteFileTool()

    with pytest.raises(PathNotFoundError):
        tool.execute(
            tool_call_id="tool-call-1",
            tool_input={
                "path": "missing_dir/example.txt",
                "content": "hello",
            },
            repository_root=repository_root,
            max_output_chars=1000,
        )


def test_rejects_parent_directory_escape(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    tool = WriteFileTool()

    with pytest.raises(PathSecurityError):
        tool.execute(
            tool_call_id="tool-call-1",
            tool_input={
                "path": "../outside.txt",
                "content": "hello",
            },
            repository_root=repository_root,
            max_output_chars=1000,
        )

    assert not (tmp_path / "outside.txt").exists()


def test_rejects_absolute_path_outside_repository(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    outside_file = tmp_path / "outside.txt"

    tool = WriteFileTool()

    with pytest.raises(PathSecurityError):
        tool.execute(
            tool_call_id="tool-call-1",
            tool_input={
                "path": str(outside_file),
                "content": "hello",
            },
            repository_root=repository_root,
            max_output_chars=1000,
        )

    assert not outside_file.exists()


def test_rejects_symbolic_link_parent_escape(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    outside_directory = tmp_path / "outside"
    outside_directory.mkdir()

    symbolic_link = repository_root / "escape-link"

    try:
        symbolic_link.symlink_to(
            outside_directory,
            target_is_directory=True,
        )
    except OSError:
        pytest.skip("Symbolic links are unavailable.")

    tool = WriteFileTool()

    with pytest.raises(PathSecurityError):
        tool.execute(
            tool_call_id="tool-call-1",
            tool_input={
                "path": "escape-link/secret.txt",
                "content": "hello",
            },
            repository_root=repository_root,
            max_output_chars=1000,
        )

    assert not (outside_directory / "secret.txt").exists()


def test_rejects_symbolic_link_target_escape(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    outside_file = tmp_path / "secret.txt"
    outside_file.write_text("secret", encoding="utf-8")

    symbolic_link = repository_root / "escape-link.txt"
    symbolic_link.symlink_to(outside_file)

    tool = WriteFileTool()

    with pytest.raises(PathSecurityError):
        tool.execute(
            tool_call_id="tool-call-1",
            tool_input={
                "path": "escape-link.txt",
                "content": "overwritten",
                "mode": "overwrite",
            },
            repository_root=repository_root,
            max_output_chars=1000,
        )

    assert outside_file.read_text(encoding="utf-8") == "secret"


@pytest.mark.parametrize(
    "sensitive_path",
    [
        ".git/config",
        ".env",
        ".env.local",
        "id_rsa",
        "id_ed25519",
        "secrets/id_rsa",
        "server.pem",
        "server.key",
        ".venv/pyvenv.cfg",
        "venv/pyvenv.cfg",
        "__pycache__/module.pyc",
    ],
)
def test_rejects_sensitive_paths(
    tmp_path: Path,
    sensitive_path: str,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()
    (repository_root / Path(sensitive_path).parent).mkdir(
        parents=True, exist_ok=True
    )

    tool = WriteFileTool()

    with pytest.raises(SensitivePathToolError):
        tool.execute(
            tool_call_id="tool-call-1",
            tool_input={
                "path": sensitive_path,
                "content": "hello",
            },
            repository_root=repository_root,
            max_output_chars=1000,
        )


def test_rejects_content_over_write_size_limit(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    tool = WriteFileTool(max_write_bytes=5)

    with pytest.raises(WriteSizeLimitToolError):
        tool.execute(
            tool_call_id="tool-call-1",
            tool_input={
                "path": "example.txt",
                "content": "too long",
            },
            repository_root=repository_root,
            max_output_chars=1000,
        )

    assert not (repository_root / "example.txt").exists()


def test_does_not_leave_temporary_file_behind(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    tool = WriteFileTool()

    tool.execute(
        tool_call_id="tool-call-1",
        tool_input={
            "path": "example.txt",
            "content": "hello",
        },
        repository_root=repository_root,
        max_output_chars=1000,
    )

    assert list(repository_root.iterdir()) == [
        repository_root / "example.txt"
    ]
