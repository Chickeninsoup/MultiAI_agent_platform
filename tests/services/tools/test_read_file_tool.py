from pathlib import Path

import pytest

from src.services.tools.handlers.read_file_tool import (
    InvalidToolInputError,
    ReadFileTool,
)
from src.services.tools.path_guard import PathSecurityError


def test_reads_complete_file(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    target_file = repository_root / "example.txt"
    target_file.write_text(
        "alpha\nbeta\ngamma\n",
        encoding="utf-8",
    )

    tool = ReadFileTool()

    result = tool.execute(
        tool_call_id="tool-call-1",
        tool_input={"path": "example.txt"},
        repository_root=repository_root,
        max_output_chars=1000,
    )

    assert result.success is True
    assert result.tool_name == "read_file"
    assert result.output == "1: alpha\n2: beta\n3: gamma"
    assert result.metadata["total_lines"] == 3
    assert result.metadata["truncated"] is False


def test_reads_selected_line_range(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    target_file = repository_root / "example.txt"
    target_file.write_text(
        "alpha\nbeta\ngamma\ndelta",
        encoding="utf-8",
    )

    tool = ReadFileTool()

    result = tool.execute(
        tool_call_id="tool-call-2",
        tool_input={
            "path": "example.txt",
            "start_line": 2,
            "end_line": 3,
        },
        repository_root=repository_root,
        max_output_chars=1000,
    )

    assert result.output == "2: beta\n3: gamma"
    assert result.metadata["start_line"] == 2
    assert result.metadata["end_line"] == 3


def test_truncates_large_output(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    target_file = repository_root / "large.txt"
    target_file.write_text(
        "abcdefghij",
        encoding="utf-8",
    )

    tool = ReadFileTool()

    result = tool.execute(
        tool_call_id="tool-call-3",
        tool_input={"path": "large.txt"},
        repository_root=repository_root,
        max_output_chars=5,
    )

    assert result.output == "1: ab"
    assert result.metadata["truncated"] is True


def test_rejects_missing_path_input(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    tool = ReadFileTool()

    with pytest.raises(InvalidToolInputError):
        tool.execute(
            tool_call_id="tool-call-4",
            tool_input={},
            repository_root=repository_root,
            max_output_chars=1000,
        )


def test_rejects_invalid_line_range(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    target_file = repository_root / "example.txt"
    target_file.write_text(
        "alpha\nbeta",
        encoding="utf-8",
    )

    tool = ReadFileTool()

    with pytest.raises(InvalidToolInputError):
        tool.execute(
            tool_call_id="tool-call-5",
            tool_input={
                "path": "example.txt",
                "start_line": 3,
                "end_line": 2,
            },
            repository_root=repository_root,
            max_output_chars=1000,
        )


def test_rejects_path_escape(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    outside_file = tmp_path / "secret.txt"
    outside_file.write_text(
        "secret",
        encoding="utf-8",
    )

    tool = ReadFileTool()

    with pytest.raises(PathSecurityError):
        tool.execute(
            tool_call_id="tool-call-6",
            tool_input={"path": "../secret.txt"},
            repository_root=repository_root,
            max_output_chars=1000,
        )


def test_rejects_directory_path(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    directory = repository_root / "folder"
    directory.mkdir()

    tool = ReadFileTool()

    with pytest.raises(InvalidToolInputError):
        tool.execute(
            tool_call_id="tool-call-7",
            tool_input={"path": "folder"},
            repository_root=repository_root,
            max_output_chars=1000,
        )


def test_rejects_unexpected_input_field(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    target_file = repository_root / "example.txt"
    target_file.write_text(
        "hello",
        encoding="utf-8",
    )

    tool = ReadFileTool()

    with pytest.raises(InvalidToolInputError):
        tool.execute(
            tool_call_id="tool-call-8",
            tool_input={
                "path": "example.txt",
                "unknown": True,
            },
            repository_root=repository_root,
            max_output_chars=1000,
        )