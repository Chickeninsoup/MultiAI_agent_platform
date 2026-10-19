from __future__ import annotations

import dataclasses

import pytest

from src.approval_pause import ApprovalPause


def test_basic_construction() -> None:
    pause = ApprovalPause(
        approval_id="approval-1",
        run_id="run-007",
        tool_call_id="toolu_1",
    )

    assert pause.approval_id == "approval-1"
    assert pause.run_id == "run-007"
    assert pause.tool_call_id == "toolu_1"


def test_pause_is_immutable() -> None:
    pause = ApprovalPause(
        approval_id="approval-1",
        run_id="run-007",
        tool_call_id="toolu_1",
    )

    with pytest.raises(dataclasses.FrozenInstanceError):
        pause.approval_id = "changed"  # type: ignore[misc]


@pytest.mark.parametrize(
    "field_name", ["approval_id", "run_id", "tool_call_id"]
)
def test_empty_fields_are_rejected(field_name: str) -> None:
    defaults = {
        "approval_id": "approval-1",
        "run_id": "run-007",
        "tool_call_id": "toolu_1",
    }
    defaults[field_name] = ""

    with pytest.raises(ValueError):
        ApprovalPause(**defaults)


@pytest.mark.parametrize(
    "field_name", ["approval_id", "run_id", "tool_call_id"]
)
def test_whitespace_only_fields_are_rejected(field_name: str) -> None:
    defaults = {
        "approval_id": "approval-1",
        "run_id": "run-007",
        "tool_call_id": "toolu_1",
    }
    defaults[field_name] = "   "

    with pytest.raises(ValueError):
        ApprovalPause(**defaults)


def test_repr_contains_no_extra_fields() -> None:
    pause = ApprovalPause(
        approval_id="approval-1",
        run_id="run-007",
        tool_call_id="toolu_1",
    )

    serialized = repr(pause)

    assert "approval-1" in serialized
    assert "run-007" in serialized
    assert "toolu_1" in serialized
