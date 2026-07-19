from __future__ import annotations

from typing import Any

import anthropic

from src.llm.base import LLMProvider
from src.llm.exceptions import (
    LLMAuthenticationError,
    LLMConnectionError,
    LLMPermissionError,
    LLMProviderError,
    LLMRateLimitError,
    LLMRequestError,
)
from src.llm.types import (
    LLMContentBlock,
    LLMRequest,
    LLMResponse,
    LLMTextBlock,
    LLMThinkingBlock,
    LLMToolUseBlock,
    LLMUsage,
)


class AnthropicProvider(LLMProvider):
    """Anthropic implementation of the LLM provider interface."""

    def __init__(
        self,
        *,
        api_key: str,
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

        self._client = anthropic.Anthropic(
            api_key=api_key,
            timeout=timeout_seconds,
            max_retries=max_retries,
        )

    @property
    def provider_name(self) -> str:
        return "anthropic"

    def complete(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        request_arguments: dict[str, Any] = {
            "model": request.model,
            "max_tokens": request.max_tokens,
            "system": request.system_prompt,
            "messages": [
                {
                    "role": message.role,
                    "content": message.content,
                }
                for message in request.messages
            ],
        }

        if request.tools:
            request_arguments["tools"] = [
                self._serialize_tool_definition(tool)
                for tool in request.tools
            ]

        try:
            response = self._client.messages.create(
                **request_arguments
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
                f"Anthropic API request failed: {error}"
            ) from error

        return LLMResponse(
            content=[
                self._parse_content_block(block)
                for block in response.content
                if self._supports_content_block(block)
            ],
            stop_reason=response.stop_reason,
            usage=LLMUsage(
                input_tokens=response.usage.input_tokens,
                output_tokens=response.usage.output_tokens,
            ),
        )

    @staticmethod
    def _serialize_tool_definition(
        tool: Any,
    ) -> dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description,
            "input_schema": tool.input_schema,
        }

    @staticmethod
    def _supports_content_block(block: Any) -> bool:
        return block.type in {
            "text",
            "thinking",
            "tool_use",
        }

    @staticmethod
    def _parse_content_block(
        block: Any,
    ) -> LLMContentBlock:
        if block.type == "text":
            return LLMTextBlock(
                type="text",
                text=block.text,
            )

        if block.type == "thinking":
            return LLMThinkingBlock(
                type="thinking",
                thinking=block.thinking,
                signature=block.signature,
            )

        if block.type == "tool_use":
            raw_input = block.input

            if not isinstance(raw_input, dict):
                raise LLMProviderError(
                    "Anthropic returned tool input "
                    "that was not an object."
                )

            return LLMToolUseBlock(
                type="tool_use",
                id=block.id,
                name=block.name,
                input=raw_input,
            )

        raise LLMProviderError(
            f"Unsupported Anthropic content block: "
            f"{block.type}"
        )