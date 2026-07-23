from __future__ import annotations

from typing import Literal

from src.llm.exceptions import (
    LLMAuthenticationError,
    LLMConfigurationError,
    LLMConnectionError,
    LLMPermissionError,
    LLMProviderError,
    LLMRateLimitError,
)
from src.llm_executor import LLMRunLimitError

RunErrorCategory = Literal[
    "LIMIT_EXCEEDED",
    "PROVIDER_ERROR",
    "TOOL_ERROR",
    "CONFIGURATION_ERROR",
    "INTERRUPTED",
    "INTERNAL_ERROR",
]

_RETRYABLE_BY_CATEGORY: dict[RunErrorCategory, bool] = {
    "LIMIT_EXCEEDED": True,
    "PROVIDER_ERROR": True,
    "TOOL_ERROR": True,
    "CONFIGURATION_ERROR": False,
    "INTERRUPTED": True,
    "INTERNAL_ERROR": False,
}


def is_retryable(category: RunErrorCategory) -> bool:
    return _RETRYABLE_BY_CATEGORY[category]


def classify_error(error: Exception) -> RunErrorCategory:
    """Map a raised exception to a run-failure category.

    Only covers exceptions that can actually reach RunService today.
    Tool-level failures never raise this far (ToolExecutor always
    converts them into a failed ToolResult instead), so TOOL_ERROR has
    no classification rule yet; it exists in the taxonomy for when that
    changes. INTERRUPTED is never produced here either — it is set
    directly by RunService.resume() when it finds a run that a crashed
    process never got the chance to mark terminal.
    """

    if isinstance(error, LLMRunLimitError):
        return "LIMIT_EXCEEDED"

    if isinstance(
        error,
        (
            LLMConfigurationError,
            LLMAuthenticationError,
            LLMPermissionError,
        ),
    ):
        return "CONFIGURATION_ERROR"

    if isinstance(
        error,
        (
            LLMProviderError,
            LLMRateLimitError,
            LLMConnectionError,
        ),
    ):
        return "PROVIDER_ERROR"

    return "INTERNAL_ERROR"
