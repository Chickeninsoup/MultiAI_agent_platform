from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

from src.services.tools.test_policy import TestDefinition


@dataclass(frozen=True)
class TestRunResult:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


class TestRunner:
    def run(
        self,
        *,
        repository_root: Path,
        test_definition: TestDefinition,
    ) -> TestRunResult:
        try:
            completed = subprocess.run(
                test_definition.command,
                cwd=repository_root,
                capture_output=True,
                text=True,
                timeout=test_definition.timeout_seconds,
            )
        except subprocess.TimeoutExpired as error:
            return TestRunResult(
                exit_code=-1,
                stdout=self._truncate(
                    error.stdout or "",
                    test_definition,
                ),
                stderr=self._truncate(
                    error.stderr or "",
                    test_definition,
                ),
                timed_out=True,
            )

        return TestRunResult(
            exit_code=completed.returncode,
            stdout=self._truncate(
                completed.stdout,
                test_definition,
            ),
            stderr=self._truncate(
                completed.stderr,
                test_definition,
            ),
            timed_out=False,
        )

    @staticmethod
    def _truncate(
        value: str,
        definition: TestDefinition,
    ) -> str:
        max_chars = definition.max_output_chars

        if len(value) <= max_chars:
            return value

        return value[:max_chars] + "\n...[output truncated]"
