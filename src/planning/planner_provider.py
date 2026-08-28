from typing import Protocol


class PlannerProvider(Protocol):
    """Something that can turn a prompt into raw text output.

    Structural, matching this codebase's Planner/HistorySizeEstimator
    convention. Deliberately not AnthropicProvider/LLMProvider
    (src/llm/base.py) directly - those speak in LLMRequest/LLMResponse
    (system prompt, tool blocks, usage). ClaudePlanner just needs
    "give me text back for this prompt," so it depends on the
    smallest interface that says that, not the full chat-completion
    contract the runtime execution loop needs.
    """

    def complete(self, prompt: str) -> str:
        ...
