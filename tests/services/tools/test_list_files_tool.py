from pathlib import Path

import pytest

from src.services.tools.handlers.list_files_tool import (
    ListFilesTool,
)
from src.services.tools.handlers.read_file_tool import (
    InvalidToolInputError,
)
from src.services.tools.path_guard import PathSecurityError


def test_lists_repository_root(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    (repository_root / "alpha.txt").write_text(
        "alpha",
        encoding="utf-8",
    )

    (repository_root / "folder").mkdir()

    tool = ListFilesTool()

    result = tool.execute(
        tool_call_id="tool-call-1",
        tool_input={},
        repository_root=repository_root,
        max_output_chars=1000,
    )

    assert result.success is True
    assert result.output == "alpha.txt\nfolder/"
    assert result.metadata["total_entries"] == 2
    assert result.metadata["recursive"] is False


def test_lists_specific_directory(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    source_directory = repository_root / "src"
    source_directory.mkdir()

    (source_directory / "main.py").write_text(
        "print('hello')",
        encoding="utf-8",
    )

    tool = ListFilesTool()

    result = tool.execute(
        tool_call_id="tool-call-2",
        tool_input={"path": "src"},
        repository_root=repository_root,
        max_output_chars=1000,
    )

    assert result.output == "src/main.py"


def test_lists_recursively(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    source_directory = repository_root / "src"
    source_directory.mkdir()

    nested_directory = source_directory / "services"
    nested_directory.mkdir()

    (source_directory / "main.py").write_text(
        "main",
        encoding="utf-8",
    )

    (nested_directory / "worker.py").write_text(
        "worker",
        encoding="utf-8",
    )

    tool = ListFilesTool()

    result = tool.execute(
        tool_call_id="tool-call-3",
        tool_input={
            "path": ".",
            "recursive": True,
        },
        repository_root=repository_root,
        max_output_chars=1000,
    )

    assert result.output == (
        "src/\n"
        "src/main.py\n"
        "src/services/\n"
        "src/services/worker.py"
    )


def test_skips_git_directory(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    git_directory = repository_root / ".git"
    git_directory.mkdir()

    (git_directory / "config").write_text(
        "secret",
        encoding="utf-8",
    )

    (repository_root / "README.md").write_text(
        "hello",
        encoding="utf-8",
    )

    tool = ListFilesTool()

    result = tool.execute(
        tool_call_id="tool-call-4",
        tool_input={
            "recursive": True,
        },
        repository_root=repository_root,
        max_output_chars=1000,
    )

    assert result.output == "README.md"
    assert ".git" not in result.output


def test_rejects_file_path(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    target_file = repository_root / "example.txt"
    target_file.write_text(
        "hello",
        encoding="utf-8",
    )

    tool = ListFilesTool()

    with pytest.raises(InvalidToolInputError):
        tool.execute(
            tool_call_id="tool-call-5",
            tool_input={"path": "example.txt"},
            repository_root=repository_root,
            max_output_chars=1000,
        )


def test_rejects_path_escape(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    outside_directory = tmp_path / "outside"
    outside_directory.mkdir()

    tool = ListFilesTool()

    with pytest.raises(PathSecurityError):
        tool.execute(
            tool_call_id="tool-call-6",
            tool_input={"path": "../outside"},
            repository_root=repository_root,
            max_output_chars=1000,
        )


def test_rejects_invalid_recursive_value(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    tool = ListFilesTool()

    with pytest.raises(InvalidToolInputError):
        tool.execute(
            tool_call_id="tool-call-7",
            tool_input={"recursive": "yes"},
            repository_root=repository_root,
            max_output_chars=1000,
        )


def test_truncates_output(tmp_path: Path) -> None:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    (repository_root / "abcdefghij.txt").write_text(
        "hello",
        encoding="utf-8",
    )

    tool = ListFilesTool()

    result = tool.execute(
        tool_call_id="tool-call-8",
        tool_input={},
        repository_root=repository_root,
        max_output_chars=5,
    )

    assert result.output == "abcde"
    assert result.metadata["truncated"] is True
