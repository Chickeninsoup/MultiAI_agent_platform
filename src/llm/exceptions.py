class LLMError(Exception):
    """Base exception for LLM provider failures."""


class LLMConfigurationError(LLMError):
    """Raised when provider configuration is invalid."""


class LLMAuthenticationError(LLMError):
    """Raised when provider authentication fails."""


class LLMPermissionError(LLMError):
    """Raised when a provider rejects the request."""


class LLMRateLimitError(LLMError):
    """Raised when a provider rate limit is reached."""


class LLMRequestError(LLMError):
    """Raised when a provider rejects request content."""


class LLMConnectionError(LLMError):
    """Raised when the provider cannot be reached."""


class LLMProviderError(LLMError):
    """Raised for an unclassified provider failure."""
