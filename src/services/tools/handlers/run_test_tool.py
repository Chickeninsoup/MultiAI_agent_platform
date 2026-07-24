from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult
from src.services.tools.handlers.read_file_tool import (
    InvalidToolInputError,
)
from src.services.tools.test_policy import TestPolicy
from src.services.tools.test_runner import TestRunner


@dataclass(frozen=True)
class RunTestInput:
    test_name: str


class RunTestTool:
    definition = ToolDefinition(
        name="run_test",
        description=(
            "Run an allowed, predefined project test command "
            "(for example, the unit test suite or a compile "
            "check). Only test names registered in the "
            "platform's test policy can be executed — arbitrary "
            "shell commands are never accepted."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "test_name": {
                    "type": "string",
                    "description": (
                        "Name of the allowed test to run, e.g. "
                        "'unit' or 'compile'."
                    ),
                },
            },
            "required": [
                "test_name",
            ],
            "additionalProperties": False,
        },
    )

    def __init__(
        self,
        *,
        test_policy: TestPolicy,
        test_runner: TestRunner,
    ) -> None:
        self._test_policy = test_policy
        self._test_runner = test_runner

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

        test_definition = self._test_policy.get_test(
            parsed_input.test_name
        )

        result = self._test_runner.run(
            repository_root=repository_root,
            test_definition=test_definition,
        )

        return ToolResult(
            tool_call_id=tool_call_id,
            tool_name=self.definition.name,
            success=True,
            output=result.stdout + "\n" + result.stderr,
            metadata={
                "test_name": parsed_input.test_name,
                "exit_code": result.exit_code,
                "timed_out": result.timed_out,
            },
        )

    @staticmethod
    def validate_input(
        tool_input: dict[str, Any],
    ) -> RunTestInput:
        if not isinstance(tool_input, dict):
            raise InvalidToolInputError(
                "Tool input must be an object."
            )

        allowed_keys = {"test_name"}
        unexpected_keys = set(tool_input) - allowed_keys

        if unexpected_keys:
            unexpected = ", ".join(sorted(unexpected_keys))
            raise InvalidToolInputError(
                f"Unexpected input fields: {unexpected}"
            )

        test_name_value = tool_input.get("test_name")

        if (
            not isinstance(test_name_value, str)
            or not test_name_value.strip()
        ):
            raise InvalidToolInputError(
                "'test_name' must be a non-empty string."
            )

        if "\x00" in test_name_value:
            raise InvalidToolInputError(
                "'test_name' must not contain null characters."
            )

        return RunTestInput(test_name=test_name_value)
