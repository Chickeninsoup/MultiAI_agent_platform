from __future__ import annotations

import pytest

from src.approval_errors import InvalidApprovalIdError
from src.approval_id import validate_approval_id


@pytest.mark.parametrize(
    "approval_id",
    [
        "approval-1",
        "approval_1",
        "a",
        "A1_-",
        "approval-" + "a" * 64,
        "x" * 128,
    ],
)
def test_safe_ids_are_accepted(approval_id: str) -> None:
    validate_approval_id(approval_id)


@pytest.mark.parametrize(
    "approval_id",
    [
        "",
        "   ",
        ".",
        "..",
        "../outside",
        "../../task",
        "/absolute/path",
        "a/b",
        "a\\b",
        "a b",
        "a\tb",
        "a\nb",
        "a\x00b",
        "x" * 129,
    ],
)
def test_unsafe_ids_are_rejected(approval_id: str) -> None:
    with pytest.raises(InvalidApprovalIdError):
        validate_approval_id(approval_id)
