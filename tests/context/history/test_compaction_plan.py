from __future__ import annotations

import dataclasses

import pytest

from src.context.history.compaction_plan import CompactionPlan


def test_compaction_plan_holds_original_count_and_retained_indices() -> (
    None
):
    plan = CompactionPlan(original_count=5, retained_indices=[0, 1, 4])

    assert plan.original_count == 5
    assert plan.retained_indices == [0, 1, 4]


def test_retained_indices_defaults_to_empty_list() -> None:
    plan = CompactionPlan(original_count=5)

    assert plan.retained_indices == []


def test_compaction_plan_is_frozen() -> None:
    plan = CompactionPlan(original_count=5, retained_indices=[0, 1, 4])

    with pytest.raises(dataclasses.FrozenInstanceError):
        plan.original_count = 10
