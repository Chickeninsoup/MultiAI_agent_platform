from typing import Protocol

from src.llm.types import LLMRequest, LLMResponse


class LLMProvider(Protocol):
    """Provider-independent interface for language models."""

    @property
    def provider_name(self) -> str:
        ...

    def complete(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        ...
