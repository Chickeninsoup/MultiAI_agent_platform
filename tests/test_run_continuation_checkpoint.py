from __future__ import annotations

import dataclasses

import pytest

from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_result import ToolResult
from src.llm.types import LLMMessage
from src.run_continuation_checkpoint import (
    CHECKPOINT_SCHEMA_VERSION,
    RunContinuationCheckpoint,
)
from src.run_continuation_checkpoint_errors import (
    UnsupportedCheckpointVersionError,
)


def _tool_call(id_: str, name: str = "write_file") -> ToolCall:
    return ToolCall(id=id_, name=name, input={"path": f"{id_}.py"})


def _tool_result(id_: str) -> ToolResult:
    return ToolResult(
        tool_call_id=id_, tool_name="write_file", success=True, output="ok"
    )


def _checkpoint(**overrides: object) -> RunContinuationCheckpoint:
    defaults: dict[str, object] = {
        "schema_version": CHECKPOINT_SCHEMA_VERSION,
        "task_id": "task-1",
        "run_id": "run-007",
        "approval_id": "approval-1",
        "messages": (
            LLMMessage(role="user", content="do the task"),
            LLMMessage(
                role="assistant",
                content=[
                    {
                        "type": "tool_use",
                        "id": "toolu_a",
                        "name": "read_file",
                        "input": {"path": "a.py"},
                    },
                    {
                        "type": "tool_use",
                        "id": "toolu_b",
                        "name": "write_file",
                        "input": {"path": "b.py", "content": "x"},
                    },
                ],
            ),
        ),
        "pending_round_tool_calls": (
            _tool_call("toolu_a", "read_file"),
            _tool_call("toolu_b", "write_file"),
        ),
        "pending_tool_call_index": 1,
        "pending_tool_call_id": "toolu_b",
        "completed_tool_results": (_tool_result("toolu_a"),),
        "llm_rounds": 1,
        "tool_rounds": 1,
        "cumulative_tool_calls": 2,
        "total_input_tokens": 10,
        "total_output_tokens": 5,
        "max_tool_rounds": 8,
        "max_total_tokens": 100_000,
        "created_at": "2026-01-01T00:00:00Z",
    }
    defaults.update(overrides)

    return RunContinuationCheckpoint(**defaults)  # type: ignore[arg-type]


def test_valid_construction() -> None:
    checkpoint = _checkpoint()

    assert checkpoint.task_id == "task-1"
    assert checkpoint.run_id == "run-007"
    assert checkpoint.approval_id == "approval-1"
    assert checkpoint.pending_tool_call_index == 1
    assert checkpoint.pending_tool_call_id == "toolu_b"
    assert len(checkpoint.completed_tool_results) == 1


def test_checkpoint_is_frozen() -> None:
    checkpoint = _checkpoint()

    with pytest.raises(dataclasses.FrozenInstanceError):
        checkpoint.run_id = "changed"  # type: ignore[misc]


def test_to_dict_and_from_dict_roundtrip() -> None:
    checkpoint = _checkpoint()

    assert (
        RunContinuationCheckpoint.from_dict(checkpoint.to_dict())
        == checkpoint
    )


@pytest.mark.parametrize(
    "field_name", ["task_id", "run_id", "approval_id", "pending_tool_call_id"]
)
def test_empty_required_identifiers_are_rejected(field_name: str) -> None:
    with pytest.raises(ValueError):
        _checkpoint(**{field_name: ""})


def test_unsupported_version_is_rejected() -> None:
    with pytest.raises(UnsupportedCheckpointVersionError):
        _checkpoint(schema_version=999)


def test_from_dict_rejects_unsupported_version() -> None:
    checkpoint = _checkpoint()
    data = checkpoint.to_dict()
    data["schema_version"] = 999

    with pytest.raises(UnsupportedCheckpointVersionError):
        RunContinuationCheckpoint.from_dict(data)


def test_out_of_range_pending_index_is_rejected() -> None:
    with pytest.raises(ValueError):
        _checkpoint(pending_tool_call_index=5)


def test_negative_pending_index_is_rejected() -> None:
    with pytest.raises(ValueError):
        _checkpoint(pending_tool_call_index=-1)


def test_pending_tool_call_id_must_match_the_indexed_call() -> None:
    with pytest.raises(ValueError):
        _checkpoint(pending_tool_call_id="toolu_wrong")


def test_completed_tool_results_length_must_match_pending_index() -> None:
    with pytest.raises(ValueError):
        _checkpoint(
            completed_tool_results=(
                _tool_result("toolu_a"),
                _tool_result("toolu_extra"),
            )
        )


def test_empty_completed_tool_results_valid_when_pending_index_is_zero() -> (
    None
):
    checkpoint = _checkpoint(
        pending_tool_call_index=0,
        pending_tool_call_id="toolu_a",
        completed_tool_results=(),
    )

    assert checkpoint.completed_tool_results == ()


def test_missing_field_raises_explicitly() -> None:
    data = _checkpoint().to_dict()
    del data["approval_id"]

    with pytest.raises(KeyError):
        RunContinuationCheckpoint.from_dict(data)


def test_repr_excludes_sensitive_fields() -> None:
    checkpoint = _checkpoint()

    serialized = repr(checkpoint)

    assert "messages" not in serialized
    assert "pending_round_tool_calls" not in serialized
    assert "completed_tool_results" not in serialized
    assert "toolu_a" not in serialized
    assert "b.py" not in serialized


def test_repr_still_shows_safe_identifiers() -> None:
    checkpoint = _checkpoint()

    serialized = repr(checkpoint)

    assert "task-1" in serialized
    assert "run-007" in serialized
    assert "approval-1" in serialized
    assert "toolu_b" in serialized
