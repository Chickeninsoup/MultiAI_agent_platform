from __future__ import annotations

import dataclasses

import pytest

from src.context.context_budget import ContextBudget


def test_context_budget_holds_max_tokens() -> None:
    budget = ContextBudget(max_tokens=10000)

    assert budget.max_tokens == 10000


def test_context_budget_is_frozen() -> None:
    budget = ContextBudget(max_tokens=10000)

    with pytest.raises(dataclasses.FrozenInstanceError):
        budget.max_tokens = 20000


def test_context_budget_allows_zero_max_tokens() -> None:
    budget = ContextBudget(max_tokens=0)

    assert budget.max_tokens == 0
