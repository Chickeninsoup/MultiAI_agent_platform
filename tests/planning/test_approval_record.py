from __future__ import annotations

import dataclasses

import pytest

from src.planning.approval_record import ApprovalRecord


def test_default_pending() -> None:
    record = ApprovalRecord(task_id="task-1")

    assert record.status == "pending"


def test_can_create_approved() -> None:
    record = ApprovalRecord(task_id="task-1", status="approved")

    assert record.status == "approved"


def test_can_create_rejected() -> None:
    record = ApprovalRecord(task_id="task-1", status="rejected")

    assert record.status == "rejected"


def test_created_at_defaults_to_a_non_empty_string() -> None:
    record = ApprovalRecord(task_id="task-1")

    assert isinstance(record.created_at, str)
    assert record.created_at != ""


def test_frozen() -> None:
    record = ApprovalRecord(task_id="task-1")

    with pytest.raises(dataclasses.FrozenInstanceError):
        record.status = "approved"


def test_status_change_produces_a_new_record() -> None:
    record = ApprovalRecord(task_id="task-1")

    updated = dataclasses.replace(record, status="approved")

    assert record.status == "pending"
    assert updated.status == "approved"
    assert updated is not record
