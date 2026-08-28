from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HistoryBudget:
    """The max tokens a compacted conversation history may occupy.

    Deliberately its own type, not ContextBudget reused - the two
    guard different things: ContextBudget caps the static file
    selection built once per request (src/context/context_budget.py),
    this caps the dynamic, growing conversation history a
    HistoryCompactor packs groups into. They're free to diverge (e.g.
    different defaults, different callers) without either dragging
    the other along. Neither of these is settings.llm_max_total_tokens
    in llm_executor.py either - that's a third, separate concept: the
    cumulative spend ceiling across every round of a run, not a size
    cap on any one thing sent to the provider.
    """

    max_tokens: int
