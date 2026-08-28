from __future__ import annotations

from src.llm.types import LLMMessage

_CHARACTERS_PER_TOKEN = 4


class CharBasedHistorySizeEstimator:
    """Provider-independent len(text) // 4 heuristic. No API call.

    Fast and dependency-free, but NOT a guarantee against any real
    provider's context window - Phase 1 Step 4's smoke test measured
    a ~2x gap against Anthropic's actual reported input_tokens for
    the same content (this heuristic also has no idea tool
    definitions exist at all, since those never pass through here).
    Use this as a deterministic fallback/default; swap in a real
    provider-tokenizer-backed HistorySizeEstimator (e.g. Anthropic's
    count_tokens) when a budget needs to hold against the provider's
    actual context window, not just relative comparisons between
    groups.
    """

    def estimate(self, messages: list[LLMMessage]) -> int:
        chars = sum(len(str(message)) for message in messages)

        return max(1, chars // _CHARACTERS_PER_TOKEN)
