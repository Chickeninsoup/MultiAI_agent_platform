import json
from pathlib import Path

import pytest

from src.services.tools.test_policy import (
    TestPolicyError,
    UnknownTestError,
    parse_test_policy,
    TestPolicy,
)


def test_load_policy(tmp_path: Path) -> None:
    policy_file = tmp_path / "test_policy.json"
    policy_file.write_text(
        json.dumps(
            {
                "tests": {
                    "unit": {
                        "command": [
                            "python",
                            "-m",
                            "pytest",
                        ],
                        "timeout_seconds": 100,
                        "max_output_chars": 5000,
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    policy = TestPolicy.load(policy_file)

    test = policy.get_test("unit")

    assert test.command == ["python", "-m", "pytest"]
    assert test.timeout_seconds == 100
    assert test.max_output_chars == 5000


def test_loads_multiple_tests() -> None:
    policy = parse_test_policy(
        {
            "tests": {
                "unit": {
                    "command": ["python", "-m", "pytest", "-q"],
                    "timeout_seconds": 120,
                    "max_output_chars": 10000,
                },
                "compile": {
                    "command": [
                        "python",
                        "-m",
                        "compileall",
                        "src",
                    ],
                    "timeout_seconds": 60,
                    "max_output_chars": 10000,
                },
            }
        }
    )

    assert policy.get_test("unit").command == [
        "python",
        "-m",
        "pytest",
        "-q",
    ]
    assert policy.get_test("compile").command == [
        "python",
        "-m",
        "compileall",
        "src",
    ]


def test_unknown_test_rejected() -> None:
    policy = parse_test_policy(
        {
            "tests": {
                "unit": {
                    "command": ["python", "-m", "pytest"],
                    "timeout_seconds": 100,
                    "max_output_chars": 5000,
                }
            }
        }
    )

    with pytest.raises(UnknownTestError):
        policy.get_test("does_not_exist")


def test_load_missing_file_raises(tmp_path: Path) -> None:
    with pytest.raises(TestPolicyError):
        TestPolicy.load(tmp_path / "missing.json")


def test_load_invalid_json_raises(tmp_path: Path) -> None:
    policy_file = tmp_path / "test_policy.json"
    policy_file.write_text("not json", encoding="utf-8")

    with pytest.raises(TestPolicyError):
        TestPolicy.load(policy_file)


def test_rejects_non_object_root() -> None:
    with pytest.raises(TestPolicyError):
        parse_test_policy([])


def test_rejects_unexpected_root_field() -> None:
    with pytest.raises(TestPolicyError):
        parse_test_policy({"tests": {}, "unexpected": True})


def test_rejects_non_object_tests() -> None:
    with pytest.raises(TestPolicyError):
        parse_test_policy({"tests": "not-an-object"})


def test_rejects_non_object_definition() -> None:
    with pytest.raises(TestPolicyError):
        parse_test_policy({"tests": {"unit": "not-an-object"}})


def test_rejects_unexpected_definition_field() -> None:
    with pytest.raises(TestPolicyError):
        parse_test_policy(
            {
                "tests": {
                    "unit": {
                        "command": ["python"],
                        "timeout_seconds": 10,
                        "max_output_chars": 100,
                        "shell": True,
                    }
                }
            }
        )


@pytest.mark.parametrize(
    "command_value",
    [
        None,
        [],
        "pytest",
        ["python", 123],
        ["python", ""],
    ],
)
def test_rejects_invalid_command(command_value: object) -> None:
    with pytest.raises(TestPolicyError):
        parse_test_policy(
            {
                "tests": {
                    "unit": {
                        "command": command_value,
                        "timeout_seconds": 10,
                        "max_output_chars": 100,
                    }
                }
            }
        )


@pytest.mark.parametrize(
    "timeout_value",
    [None, 0, -1, "10", True],
)
def test_rejects_invalid_timeout(timeout_value: object) -> None:
    with pytest.raises(TestPolicyError):
        parse_test_policy(
            {
                "tests": {
                    "unit": {
                        "command": ["python"],
                        "timeout_seconds": timeout_value,
                        "max_output_chars": 100,
                    }
                }
            }
        )


@pytest.mark.parametrize(
    "max_output_chars_value",
    [None, 0, -1, "100", True],
)
def test_rejects_invalid_max_output_chars(
    max_output_chars_value: object,
) -> None:
    with pytest.raises(TestPolicyError):
        parse_test_policy(
            {
                "tests": {
                    "unit": {
                        "command": ["python"],
                        "timeout_seconds": 10,
                        "max_output_chars": max_output_chars_value,
                    }
                }
            }
        )


def test_real_test_policy_file_loads() -> None:
    project_root = (
        Path(__file__).resolve().parent.parent.parent.parent
    )
    policy = TestPolicy.load(
        project_root / "src" / "config" / "test_policy.json"
    )

    unit_test = policy.get_test("unit")
    assert unit_test.command == [
        ".venv/bin/python",
        "-m",
        "pytest",
        "-q",
    ]

    compile_test = policy.get_test("compile")
    assert compile_test.command == [
        ".venv/bin/python",
        "-m",
        "compileall",
        "src",
    ]
