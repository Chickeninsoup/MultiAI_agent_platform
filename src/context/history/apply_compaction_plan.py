from src.context.history.compaction_plan import CompactionPlan
from src.llm.types import LLMMessage


def apply_compaction_plan(
    messages: list[LLMMessage], plan: CompactionPlan
) -> list[LLMMessage]:
    """Builds a short request-view from full history, per a CompactionPlan.

    A plain function, not a class - there's nothing here that varies
    across a LocalRuleBasedCompactor / AnthropicNativeCompactor /
    OpenAICompactor: those differ in how a CompactionPlan gets
    produced, not in how one gets applied. Never mutates or truncates
    the input list - the caller keeps the full, durable history
    separate from whatever short view actually gets sent to the
    provider (see LLMRunExecutor, which builds this view fresh every
    round without ever reassigning its own `messages` accumulator).
    """

    return [messages[index] for index in plan.retained_indices]
