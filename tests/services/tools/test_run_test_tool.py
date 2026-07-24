from pathlib import Path

import pytest

from src.services.tools.handlers.read_file_tool import (
    InvalidToolInputError,
)
from src.services.tools.handlers.run_test_tool import (
    RunTestInput,
    RunTestTool,
)
from src.services.tools.test_policy import (
    UnknownTestError,
    parse_test_policy,
)
from src.services.tools.test_runner import TestRunner


def test_definition_uses_safe_schema() -> None:
    definition = RunTestTool.definition

    assert definition.name == "run_test"
    assert definition.input_schema["required"] == ["test_name"]
    assert definition.input_schema["additionalProperties"] is False


def test_valid_input() -> None:
    result = RunTestTool.validate_input({"test_name": "unit"})

    assert result == RunTestInput(test_name="unit")


@pytest.mark.parametrize(
    "tool_input",
    [
        None,
        [],
        "unit",
        123,
    ],
)
def test_reject_non_object(tool_input: object) -> None:
    with pytest.raises(InvalidToolInputError):
        RunTestTool.validate_input(tool_input)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "test_name_value",
    [
        None,
        "",
        "   ",
        123,
        True,
        [],
    ],
)
def test_reject_invalid_test_name(
    test_name_value: object,
) -> None:
    with pytest.raises(InvalidToolInputError):
        RunTestTool.validate_input({"test_name": test_name_value})


def test_reject_null_byte_in_test_name() -> None:
    with pytest.raises(InvalidToolInputError):
        RunTestTool.validate_input({"test_name": "unit\x00"})


def test_reject_missing_test_name() -> None:
    with pytest.raises(InvalidToolInputError):
        RunTestTool.validate_input({})


def test_reject_extra_fields() -> None:
    with pytest.raises(InvalidToolInputError):
        RunTestTool.validate_input(
            {
                "test_name": "unit",
                "command": "rm -rf .",
            }
        )


def _build_tool() -> RunTestTool:
    test_policy = parse_test_policy(
        {
            "tests": {
                "success": {
                    "command": [
                        "python",
                        "-c",
                        "print('hello')",
                    ],
                    "timeout_seconds": 10,
                    "max_output_chars": 1000,
                },
                "failure": {
                    "command": [
                        "python",
                        "-c",
                        "raise SystemExit(1)",
                    ],
                    "timeout_seconds": 10,
                    "max_output_chars": 1000,
                },
                "hangs": {
                    "command": [
                        "python",
                        "-c",
                        "import time;time.sleep(5)",
                    ],
                    "timeout_seconds": 1,
                    "max_output_chars": 1000,
                },
            }
        }
    )

    return RunTestTool(
        test_policy=test_policy,
        test_runner=TestRunner(),
    )


def test_execute_reports_successful_test(
    tmp_path: Path,
) -> None:
    result = _build_tool().execute(
        tool_call_id="call-1",
        tool_input={"test_name": "success"},
        repository_root=tmp_path,
        max_output_chars=1000,
    )

    assert result.success is True
    assert result.tool_name == "run_test"
    assert result.metadata["exit_code"] == 0
    assert result.metadata["timed_out"] is False
    assert "hello" in result.output


def test_execute_reports_failing_test_as_tool_success(
    tmp_path: Path,
) -> None:
    result = _build_tool().execute(
        tool_call_id="call-1",
        tool_input={"test_name": "failure"},
        repository_root=tmp_path,
        max_output_chars=1000,
    )

    # a failing test is not a tool failure: the tool ran correctly,
    # it just reports that the test did not pass.
    assert result.success is True
    assert result.metadata["exit_code"] == 1


def test_execute_reports_timeout(tmp_path: Path) -> None:
    result = _build_tool().execute(
        tool_call_id="call-1",
        tool_input={"test_name": "hangs"},
        repository_root=tmp_path,
        max_output_chars=1000,
    )

    assert result.success is True
    assert result.metadata["timed_out"] is True


def test_execute_rejects_unknown_test_name(
    tmp_path: Path,
) -> None:
    with pytest.raises(UnknownTestError):
        _build_tool().execute(
            tool_call_id="call-1",
            tool_input={"test_name": "does_not_exist"},
            repository_root=tmp_path,
            max_output_chars=1000,
        )


def test_execute_validates_input_before_running(
    tmp_path: Path,
) -> None:
    with pytest.raises(InvalidToolInputError):
        _build_tool().execute(
            tool_call_id="call-1",
            tool_input={},
            repository_root=tmp_path,
            max_output_chars=1000,
        )
