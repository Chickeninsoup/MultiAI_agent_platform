from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class RetryDecision:
    """Whether one ExecutionFailure is worth retrying, and why.

    reason is a required, always-populated string (not Optional) -
    both outcomes need to be explainable to a human or a log line, not
    just the "no" case. "retry" here means "worth attempting again at
    all," not a specific attempt count or backoff - that remains
    RetryPolicy/RetryManager's job (src/retry_policy.py), which this
    deliberately does not touch or extend: RetryPolicy answers "how
    many times," this answers "should we bother."
    """

    retryable: bool
    reason: str
