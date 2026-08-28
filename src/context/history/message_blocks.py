from src.llm.types import LLMMessage


def has_content_block_type(message: LLMMessage, block_type: str) -> bool:
    """True if message.content is a block list containing this type.

    Shared by RuleBasedHistoryAnalyzer (tool_result detection) and
    MessageGroupBuilder (tool_use/tool_result pairing) so the same
    content-block shape check isn't duplicated in two places.
    """

    if not isinstance(message.content, list):
        return False

    return any(
        isinstance(block, dict) and block.get("type") == block_type
        for block in message.content
    )


def get_tool_name(message: LLMMessage) -> str | None:
    """The tool name from a message's first tool_use block, if any.

    None for messages with no tool_use block (plain text, or a
    tool_result) - used by MessageGroupBuilder to tag a TOOL_EXCHANGE
    group with which tool it called, so a future retention policy
    (e.g. protecting apply_patch/write_file, evicting read_file) has
    something to key off besides "it's a tool exchange."
    """

    if not isinstance(message.content, list):
        return None

    for block in message.content:
        if isinstance(block, dict) and block.get("type") == "tool_use":
            return block.get("name")

    return None
