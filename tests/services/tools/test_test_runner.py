from pathlib import Path

from src.services.tools.test_policy import TestDefinition
from src.services.tools.test_runner import TestRunner


def test_runner_success(tmp_path: Path) -> None:
    definition = TestDefinition(
        name="success",
        command=[
            "python",
            "-c",
            "print('hello')",
        ],
        timeout_seconds=10,
        max_output_chars=1000,
    )

    result = TestRunner().run(
        repository_root=tmp_path,
        test_definition=definition,
    )

    assert result.exit_code == 0
    assert "hello" in result.stdout
    assert result.timed_out is False


def test_runner_failure(tmp_path: Path) -> None:
    definition = TestDefinition(
        name="failure",
        command=[
            "python",
            "-c",
            "raise SystemExit(1)",
        ],
        timeout_seconds=10,
        max_output_chars=1000,
    )

    result = TestRunner().run(
        repository_root=tmp_path,
        test_definition=definition,
    )

    assert result.exit_code == 1
    assert result.timed_out is False


def test_runner_captures_stderr(tmp_path: Path) -> None:
    definition = TestDefinition(
        name="stderr",
        command=[
            "python",
            "-c",
            (
                "import sys;"
                "sys.stderr.write('boom');"
                "raise SystemExit(1)"
            ),
        ],
        timeout_seconds=10,
        max_output_chars=1000,
    )

    result = TestRunner().run(
        repository_root=tmp_path,
        test_definition=definition,
    )

    assert result.exit_code == 1
    assert "boom" in result.stderr


def test_runner_timeout(tmp_path: Path) -> None:
    definition = TestDefinition(
        name="timeout",
        command=[
            "python",
            "-c",
            "import time;time.sleep(5)",
        ],
        timeout_seconds=1,
        max_output_chars=1000,
    )

    result = TestRunner().run(
        repository_root=tmp_path,
        test_definition=definition,
    )

    assert result.timed_out is True
    assert result.exit_code == -1


def test_runner_truncates_output(tmp_path: Path) -> None:
    definition = TestDefinition(
        name="large",
        command=[
            "python",
            "-c",
            "print('a' * 100)",
        ],
        timeout_seconds=10,
        max_output_chars=10,
    )

    result = TestRunner().run(
        repository_root=tmp_path,
        test_definition=definition,
    )

    assert len(result.stdout) > 10
    assert "truncated" in result.stdout


def test_runner_uses_repository_root_as_cwd(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "marker.txt"
    marker.write_text("here", encoding="utf-8")

    definition = TestDefinition(
        name="cwd-check",
        command=[
            "python",
            "-c",
            (
                "import pathlib;"
                "print(pathlib.Path('marker.txt').exists())"
            ),
        ],
        timeout_seconds=10,
        max_output_chars=1000,
    )

    result = TestRunner().run(
        repository_root=tmp_path,
        test_definition=definition,
    )

    assert result.stdout.strip() == "True"
