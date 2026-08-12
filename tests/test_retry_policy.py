from __future__ import annotations

import dataclasses

import pytest

from src.retry_policy import RetryPolicy


def test_retry_policy_defaults_max_attempts_to_one() -> None:
    policy = RetryPolicy()

    assert policy.max_attempts == 1


def test_retry_policy_can_configure_max_attempts() -> None:
    policy = RetryPolicy(max_attempts=3)

    assert policy.max_attempts == 3


def test_retry_policy_is_frozen() -> None:
    policy = RetryPolicy()

    with pytest.raises(dataclasses.FrozenInstanceError):
        policy.max_attempts = 5
