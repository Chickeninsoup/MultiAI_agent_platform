from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class TestPolicyError(Exception):
    """Raised when a test policy file is invalid."""

    error_code = "INVALID_TEST_POLICY"


class UnknownTestError(Exception):
    """Raised when a requested test name is not registered."""

    error_code = "UNKNOWN_TEST"


@dataclass(frozen=True)
class TestDefinition:
    name: str
    command: list[str]
    timeout_seconds: int
    max_output_chars: int


class TestPolicy:
    def __init__(
        self,
        tests: dict[str, TestDefinition],
    ) -> None:
        self._tests = tests

    def get_test(self, name: str) -> TestDefinition:
        if name not in self._tests:
            raise UnknownTestError(f"Unknown test: {name}")

        return self._tests[name]

    @classmethod
    def load(cls, path: Path) -> "TestPolicy":
        try:
            raw_text = path.read_text(encoding="utf-8")
        except FileNotFoundError as error:
            raise TestPolicyError(
                f"Test policy file does not exist: {path}"
            ) from error

        try:
            raw_policy = json.loads(raw_text)
        except json.JSONDecodeError as error:
            raise TestPolicyError(
                f"Test policy is not valid JSON: {path}"
            ) from error

        return parse_test_policy(raw_policy)


def parse_test_policy(raw_policy: Any) -> TestPolicy:
    if not isinstance(raw_policy, dict):
        raise TestPolicyError(
            "Test policy root must be an object."
        )

    allowed_root_keys = {"tests"}
    unexpected_root_keys = set(raw_policy) - allowed_root_keys

    if unexpected_root_keys:
        unexpected = ", ".join(sorted(unexpected_root_keys))
        raise TestPolicyError(
            f"Unexpected policy fields: {unexpected}"
        )

    raw_tests = raw_policy.get("tests")

    if not isinstance(raw_tests, dict):
        raise TestPolicyError("'tests' must be an object.")

    tests: dict[str, TestDefinition] = {}

    for name, raw_definition in raw_tests.items():
        if not isinstance(name, str) or not name:
            raise TestPolicyError(
                "Test names must be non-empty strings."
            )

        tests[name] = _parse_test_definition(
            name,
            raw_definition,
        )

    return TestPolicy(tests)


def _parse_test_definition(
    name: str,
    raw_definition: Any,
) -> TestDefinition:
    if not isinstance(raw_definition, dict):
        raise TestPolicyError(
            f"Definition for test '{name}' must be an object."
        )

    allowed_keys = {
        "command",
        "timeout_seconds",
        "max_output_chars",
    }
    unexpected_keys = set(raw_definition) - allowed_keys

    if unexpected_keys:
        unexpected = ", ".join(sorted(unexpected_keys))
        raise TestPolicyError(
            f"Unexpected fields for test '{name}': {unexpected}"
        )

    command = raw_definition.get("command")

    if (
        not isinstance(command, list)
        or not command
        or not all(
            isinstance(part, str) and part
            for part in command
        )
    ):
        raise TestPolicyError(
            f"'command' for test '{name}' must be a non-empty "
            "list of non-empty strings."
        )

    timeout_seconds = raw_definition.get("timeout_seconds")

    if (
        not isinstance(timeout_seconds, int)
        or isinstance(timeout_seconds, bool)
        or timeout_seconds < 1
    ):
        raise TestPolicyError(
            f"'timeout_seconds' for test '{name}' must be a "
            "positive integer."
        )

    max_output_chars = raw_definition.get("max_output_chars")

    if (
        not isinstance(max_output_chars, int)
        or isinstance(max_output_chars, bool)
        or max_output_chars < 1
    ):
        raise TestPolicyError(
            f"'max_output_chars' for test '{name}' must be a "
            "positive integer."
        )

    return TestDefinition(
        name=name,
        command=list(command),
        timeout_seconds=timeout_seconds,
        max_output_chars=max_output_chars,
    )
