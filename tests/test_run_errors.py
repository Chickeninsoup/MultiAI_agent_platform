from src.llm.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMPermissionError,
    LLMRateLimitError,
    LLMRequestError,
)
from src.llm_executor import LLMRunLimitError
from src.run_errors import classify_error, is_retryable


def test_limit_error_classified_as_limit_exceeded_and_retryable() -> None:
    category = classify_error(LLMRunLimitError("too many rounds"))
    assert category == "LIMIT_EXCEEDED"
    assert is_retryable(category) is True


def test_authentication_error_classified_as_configuration_not_retryable() -> None:
    category = classify_error(LLMAuthenticationError("bad key"))
    assert category == "CONFIGURATION_ERROR"
    assert is_retryable(category) is False


def test_permission_error_classified_as_configuration_not_retryable() -> None:
    category = classify_error(LLMPermissionError("denied"))
    assert category == "CONFIGURATION_ERROR"
    assert is_retryable(category) is False


def test_rate_limit_error_classified_as_provider_error_retryable() -> None:
    category = classify_error(LLMRateLimitError("slow down"))
    assert category == "PROVIDER_ERROR"
    assert is_retryable(category) is True


def test_connection_error_classified_as_provider_error_retryable() -> None:
    category = classify_error(LLMConnectionError("no network"))
    assert category == "PROVIDER_ERROR"
    assert is_retryable(category) is True


def test_unrecognized_request_error_falls_back_to_internal_not_retryable() -> None:
    category = classify_error(LLMRequestError("malformed request"))
    assert category == "INTERNAL_ERROR"
    assert is_retryable(category) is False


def test_unknown_exception_falls_back_to_internal_not_retryable() -> None:
    category = classify_error(ValueError("something else"))
    assert category == "INTERNAL_ERROR"
    assert is_retryable(category) is False
