from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    """How many times a TaskStep is allowed to be attempted.

    Just an answer to "is this worth trying again" - deliberately one
    field: backoff, retryable-error filtering, and per-agent-type
    defaults are real needs but belong to whichever stage actually
    executes a retry loop (RetryManager), not this data model.
    """

    max_attempts: int = 1

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
