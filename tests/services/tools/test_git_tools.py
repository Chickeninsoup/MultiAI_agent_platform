from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from src.services.tools.git_command import GitCommandError
from src.services.tools.handlers.git_diff_tool import GitDiffTool
from src.services.tools.handlers.git_status_tool import GitStatusTool
from src.services.tools.handlers.read_file_tool import (
    InvalidToolInputError,
)


def run_git(
    repository_root: Path,
    *arguments: str,
) -> None:
    subprocess.run(
        ["git", *arguments],
        cwd=repository_root,
        capture_output=True,
        text=True,
        check=True,
    )


def create_git_repository(tmp_path: Path) -> Path:
    repository_root = tmp_path / "repository"
    repository_root.mkdir()

    run_git(repository_root, "init")
    run_git(
        repository_root,
        "config",
        "user.email",
        "test@example.com",
    )
    run_git(
        repository_root,
        "config",
        "user.name",
        "Test User",
    )

    tracked_file = repository_root / "example.txt"
    tracked_file.write_text(
        "original\n",
        encoding="utf-8",
    )

    run_git(repository_root, "add", "example.txt")
    run_git(repository_root, "commit", "-m", "initial")

    return repository_root


def test_git_status_shows_untracked_file(
    tmp_path: Path,
) -> None:
    repository_root = create_git_repository(tmp_path)

    (repository_root / "new.txt").write_text(
        "new file",
        encoding="utf-8",
    )

    tool = GitStatusTool()

    result = tool.execute(
        tool_call_id="tool-call-status-1",
        tool_input={},
        repository_root=repository_root,
        max_output_chars=1000,
    )

    assert result.success is True
    assert "?? new.txt" in result.output
    assert result.metadata["truncated"] is False


def test_git_diff_shows_unstaged_changes(
    tmp_path: Path,
) -> None:
    repository_root = create_git_repository(tmp_path)

    tracked_file = repository_root / "example.txt"
    tracked_file.write_text(
        "changed\n",
        encoding="utf-8",
    )

    tool = GitDiffTool()

    result = tool.execute(
        tool_call_id="tool-call-diff-1",
        tool_input={"staged": False},
        repository_root=repository_root,
        max_output_chars=10000,
    )

    assert result.success is True
    assert "-original" in result.output
    assert "+changed" in result.output
    assert result.metadata["staged"] is False


def test_git_diff_shows_staged_changes(
    tmp_path: Path,
) -> None:
    repository_root = create_git_repository(tmp_path)

    tracked_file = repository_root / "example.txt"
    tracked_file.write_text(
        "staged change\n",
        encoding="utf-8",
    )

    run_git(repository_root, "add", "example.txt")

    tool = GitDiffTool()

    result = tool.execute(
        tool_call_id="tool-call-diff-2",
        tool_input={"staged": True},
        repository_root=repository_root,
        max_output_chars=10000,
    )

    assert result.success is True
    assert "+staged change" in result.output
    assert result.metadata["staged"] is True


def test_git_diff_returns_message_when_clean(
    tmp_path: Path,
) -> None:
    repository_root = create_git_repository(tmp_path)

    tool = GitDiffTool()

    result = tool.execute(
        tool_call_id="tool-call-diff-3",
        tool_input={},
        repository_root=repository_root,
        max_output_chars=1000,
    )

    assert result.output == "No differences."


def test_git_status_rejects_unexpected_input(
    tmp_path: Path,
) -> None:
    repository_root = create_git_repository(tmp_path)
    tool = GitStatusTool()

    with pytest.raises(InvalidToolInputError):
        tool.execute(
            tool_call_id="tool-call-status-2",
            tool_input={"unexpected": True},
            repository_root=repository_root,
            max_output_chars=1000,
        )


def test_git_diff_rejects_invalid_staged_value(
    tmp_path: Path,
) -> None:
    repository_root = create_git_repository(tmp_path)
    tool = GitDiffTool()

    with pytest.raises(InvalidToolInputError):
        tool.execute(
            tool_call_id="tool-call-diff-4",
            tool_input={"staged": "yes"},
            repository_root=repository_root,
            max_output_chars=1000,
        )


def test_git_tool_rejects_non_git_directory(
    tmp_path: Path,
) -> None:
    repository_root = tmp_path / "not-a-repository"
    repository_root.mkdir()

    tool = GitStatusTool()

    with pytest.raises(GitCommandError):
        tool.execute(
            tool_call_id="tool-call-status-3",
            tool_input={},
            repository_root=repository_root,
            max_output_chars=1000,
        )


def test_git_diff_truncates_output(
    tmp_path: Path,
) -> None:
    repository_root = create_git_repository(tmp_path)

    tracked_file = repository_root / "example.txt"
    tracked_file.write_text(
        "a very long changed line\n",
        encoding="utf-8",
    )

    tool = GitDiffTool()

    result = tool.execute(
        tool_call_id="tool-call-diff-5",
        tool_input={},
        repository_root=repository_root,
        max_output_chars=10,
    )

    assert len(result.output) == 10
    assert result.metadata["truncated"] is True
