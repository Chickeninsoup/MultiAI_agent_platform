from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

from src.domain.tools.tool_definition import ToolDefinition


LLMRole = Literal["user", "assistant"]


@dataclass(frozen=True)
class LLMTextBlock:
    type: Literal["text"]
    text: str


@dataclass(frozen=True)
class LLMThinkingBlock:
    type: Literal["thinking"]
    thinking: str
    signature: str


@dataclass(frozen=True)
class LLMToolUseBlock:
    type: Literal["tool_use"]
    id: str
    name: str
    input: dict[str, Any]


LLMContentBlock = (
    LLMTextBlock
    | LLMThinkingBlock
    | LLMToolUseBlock
)


@dataclass(frozen=True)
class LLMMessage:
    role: LLMRole
    content: str | list[dict[str, Any]]

    def to_dict(self) -> dict[str, Any]:
        return {"role": self.role, "content": self.content}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "LLMMessage":
        return cls(role=data["role"], content=data["content"])


@dataclass(frozen=True)
class LLMRequest:
    system_prompt: str
    messages: list[LLMMessage]
    model: str
    max_tokens: int
    tools: list[ToolDefinition] = field(default_factory=list)


@dataclass(frozen=True)
class LLMUsage:
    input_tokens: int
    output_tokens: int


@dataclass(frozen=True)
class LLMResponse:
    content: list[LLMContentBlock]
    stop_reason: str | None
    usage: LLMUsage

    @property
    def text(self) -> str:
        return "\n".join(
            block.text
            for block in self.content
            if isinstance(block, LLMTextBlock)
        )

    @property
    def tool_calls(self) -> list[LLMToolUseBlock]:
        return [
            block
            for block in self.content
            if isinstance(block, LLMToolUseBlock)
        ]

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)

    def to_message_content(self) -> list[dict[str, Any]]:
        content: list[dict[str, Any]] = []

        for block in self.content:
            if isinstance(block, LLMTextBlock):
                content.append(
                    {
                        "type": "text",
                        "text": block.text,
                    }
                )

            elif isinstance(block, LLMThinkingBlock):
                content.append(
                    {
                        "type": "thinking",
                        "thinking": block.thinking,
                        "signature": block.signature,
                    }
                )

            elif isinstance(block, LLMToolUseBlock):
                content.append(
                    {
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }
                )

        return content

        