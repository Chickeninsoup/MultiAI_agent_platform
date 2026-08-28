from __future__ import annotations

from dataclasses import dataclass

from src.step_execution_result import StepExecutionResult


@dataclass(frozen=True)
class RetryResult:
    """How many attempts RetryManager made, and what the last one produced.

    attempts counts every attempt, successful or not - a SUCCESS on
    the second try still reports attempts=2, so a caller can tell
    "worked first try" from "needed a retry" without inspecting
    final_result.attempt separately (RetryManager keeps that field in
    sync with attempts too).
    """

    attempts: int
    final_result: StepExecutionResult
