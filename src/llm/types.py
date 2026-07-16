from dataclasses import dataclass, field
from typing import Any, Literal


MessageRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class LLMMessage:
    role: MessageRole
    content: str

    def __post_init__(self) -> None:
        if not self.content.strip():
            raise ValueError(
                "LLM message content must not be empty"
            )


@dataclass(frozen=True)
class LLMRequest:
    messages: list[LLMMessage]
    model: str
    max_tokens: int
    system_prompt: str | None = None
    temperature: float | None = None
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not self.messages:
            raise ValueError(
                "LLM request must contain at least one message"
            )

        if not self.model.strip():
            raise ValueError(
                "LLM request model must not be empty"
            )

        if self.max_tokens <= 0:
            raise ValueError(
                "LLM request max_tokens must be positive"
            )

        if (
            self.temperature is not None
            and not 0.0 <= self.temperature <= 1.0
        ):
            raise ValueError(
                "LLM request temperature must be between 0 and 1"
            )


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int

    def __post_init__(self) -> None:
        if self.input_tokens < 0:
            raise ValueError(
                "Input token count must not be negative"
            )

        if self.output_tokens < 0:
            raise ValueError(
                "Output token count must not be negative"
            )


@dataclass(frozen=True)
class LLMResponse:
    text: str
    provider: str
    model: str
    usage: LLMUsage
    stop_reason: str | None
    response_id: str | None
    raw_metadata: dict[str, Any] = field(
        default_factory=dict
    )
