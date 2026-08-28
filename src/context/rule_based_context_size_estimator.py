from __future__ import annotations

from src.context.context_snapshot import ContextSnapshot

_CHARACTERS_PER_TOKEN = 4


class RuleBasedContextSizeEstimator:
    """Estimates a ContextSnapshot's token count as len(text) // 4.

    No tokenizer, no LLM API call - fast, dependency-free, good
    enough to compare against a ContextBudget. A future
    Claude-/OpenAI-tokenizer-backed estimator replaces this class
    entirely rather than this growing smarter chars-per-token math.
    Floors at 1 rather than returning 0 for an empty/trivial snapshot
    - a downstream `if estimated_tokens > budget` check should never
    treat "nothing selected" as literally zero cost.

    Important gap, carried over from 5D-6B-1's own scope decision:
    ContextFile only holds path + reason, not file content, so this
    estimates the size of the snapshot's own metadata (paths,
    reasons, project tree) - not the size of the file contents that
    will eventually be read and sent to the LLM. A snapshot naming 5
    huge files still estimates as a handful of tokens. Closing that
    gap needs ContextFile to carry size or content, which is out of
    scope here; 5D-6B-3B deliberately does file-count trimming, not
    real token-level truncation, for exactly this reason.
    """

    def estimate(self, snapshot: ContextSnapshot) -> int:
        return max(
            1, len(self._render(snapshot)) // _CHARACTERS_PER_TOKEN
        )

    def _render(self, snapshot: ContextSnapshot) -> str:
        parts = [snapshot.project_tree]
        parts.extend(
            f"{file.path}\n{file.reason}" for file in snapshot.files
        )

        return "\n".join(parts)
