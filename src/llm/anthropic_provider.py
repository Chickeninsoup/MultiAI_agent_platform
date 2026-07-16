from typing import Any

import anthropic
from anthropic import Anthropic

from src.llm.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMPermissionError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRequestError,
)
from src.llm.types import (
    LLMRequest,
    LLMResponse,
    LLMUsage,
)


class AnthropicProvider:
    """Anthropic implementation of the LLM provider interface."""

    def __init__(
        self,
        api_key: str,
        *,
        timeout_seconds: float = 60.0,
        max_retries: int = 2,
    ) -> None:
        if not api_key.strip():
            raise ValueError(
                "Anthropic API key must not be empty"
            )

        if timeout_seconds <= 0:
            raise ValueError(
                "Anthropic timeout must be positive"
            )

        if max_retries < 0:
            raise ValueError(
                "Anthropic max_retries must not be negative"
            )

        self._client = Anthropic(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def generate(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        parameters: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in request.messages
            ],
        }

        if request.system_prompt:
            parameters["system"] = request.system_prompt

        if request.temperature is not None:
            parameters["temperature"] = request.temperature

        try:
            response = self._client.messages.create(
                **parameters
            )
        except anthropic.AuthenticationError as error:
            raise LLMAuthenticationError(
                "Anthropic authentication failed"
            ) from error
        except anthropic.PermissionDeniedError as error:
            raise LLMPermissionError(
                "Anthropic rejected the request"
            ) from error
        except anthropic.RateLimitError as error:
            raise LLMRateLimitError(
                "Anthropic rate limit reached"
            ) from error
        except anthropic.BadRequestError as error:
            raise LLMRequestError(
                f"Anthropic rejected the request: {error}"
            ) from error
        except anthropic.APIConnectionError as error:
            raise LLMConnectionError(
                "Could not connect to Anthropic"
            ) from error
        except anthropic.APIError as error:
            raise LLMProviderError(
                f"Anthropic API failure: {error}"
            ) from error

        text_parts = [
            block.text
            for block in response.content
            if block.type == "text"
        ]

        return LLMResponse(
            text="\n".join(text_parts),
            provider=self.provider_name,
            model=response.model,
            usage=LLMUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
            stop_reason=response.stop_reason,
            response_id=response.id,
            raw_metadata={
                "request_metadata": dict(request.metadata),
            },
        )
