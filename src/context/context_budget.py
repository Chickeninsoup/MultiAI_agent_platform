from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ContextBudget:
    """The max tokens a single request's context may occupy.

    Just "how big can one request be" (5D-6B-3A) - not a strategy.
    warning_threshold/truncate_policy belong to whatever actually
    trims a ContextSnapshot down to fit (5D-6B-3B ContextTrimmer), not
    this model. Deliberately separate from the existing cumulative
    run-level max_total_tokens in llm_executor.py, which this doesn't
    touch or replace - that guards total spend across every round of
    a run, this guards the size of any one request within it.
    """

    max_tokens: int
