from __future__ import annotations

from src.context.context_budget import ContextBudget
from src.context.context_size_estimator import ContextSizeEstimator
from src.context.context_snapshot import ContextSnapshot


class RuleBasedContextTrimmer:
    """Drops trailing ContextFiles until the snapshot fits its budget.

    File-level trimming only (5D-6B-3B-2) - ContextFile has no
    content/token_count/score yet, so there's nothing finer to cut.
    Walks files in selector order and stops at the first one that
    would push the snapshot over budget, rather than skipping it and
    trying later files - a selector's ordering is assumed meaningful
    (e.g. best match first), so silently reordering around a big file
    would undermine that. project_tree is never trimmed here: it's
    low-cost, high-value orientation info: whether it needs its own
    size limit is 5D-6B-3C Runtime Integration's problem, not this
    trimmer's.
    """

    def __init__(self, estimator: ContextSizeEstimator) -> None:
        self._estimator = estimator

    def trim(
        self, snapshot: ContextSnapshot, budget: ContextBudget
    ) -> ContextSnapshot:
        files = []

        for context_file in snapshot.files:
            candidate = ContextSnapshot(
                files=files + [context_file],
                project_tree=snapshot.project_tree,
            )

            if self._estimator.estimate(candidate) <= budget.max_tokens:
                files.append(context_file)
            else:
                break

        return ContextSnapshot(
            files=files, project_tree=snapshot.project_tree
        )
