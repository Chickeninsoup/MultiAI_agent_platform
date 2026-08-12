from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryPolicy:
    """How many times a TaskStep is allowed to be attempted.

    Just an answer to "is this worth trying again", not a retry
    mechanism - nothing reads or acts on this yet. Deliberately one
    field: backoff, retryable-error filtering, and per-agent-type
    defaults are real needs but belong to whichever stage actually
    executes a retry loop, not this data model.
    """

    max_attempts: int = 1
