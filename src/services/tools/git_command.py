from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


class GitCommandError(Exception):
    error_code = "GIT_COMMAND_FAILED"


@dataclass(frozen=True)
class GitCommandResult:
    output: str
    truncated: bool


def run_git_command(
    *,
    repository_root: Path,
    arguments: list[str],
    max_output_chars: int,
    timeout_seconds: int = 10,
) -> GitCommandResult:
    if max_output_chars < 1:
        raise ValueError("max_output_chars must be positive.")

    try:
        completed_process = subprocess.run(
            ["git", *arguments],
            cwd=repository_root,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
            shell=False,
            timeout=timeout_seconds,
        )
    except FileNotFoundError as error:
        raise GitCommandError(
            "Git executable was not found."
        ) from error
    except subprocess.TimeoutExpired as error:
        raise GitCommandError(
            f"Git command timed out after {timeout_seconds} seconds."
        ) from error
    except OSError as error:
        raise GitCommandError(
            f"Unable to execute Git command: {error}"
        ) from error

    stdout = completed_process.stdout.strip()
    stderr = completed_process.stderr.strip()

    if completed_process.returncode != 0:
        error_message = stderr or stdout or (
            f"Git exited with code {completed_process.returncode}."
        )

        raise GitCommandError(error_message)

    output = stdout

    if stderr:
        output = (
            f"{output}\nSTDERR:\n{stderr}"
            if output
            else f"STDERR:\n{stderr}"
        )

    truncated = len(output) > max_output_chars

    return GitCommandResult(
        output=output[:max_output_chars],
        truncated=truncated,
    )
