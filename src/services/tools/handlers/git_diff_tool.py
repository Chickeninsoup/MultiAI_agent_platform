from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult


class GitDiffTool:
    """Shows changes between commits, the working tree, and the index."""

    definition = ToolDefinition(
        name="git_diff",
        description=(
            "Show changes between commits, the working tree, "
            "and the index."
        ),
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository path to diff.",
                },
            },
            "required": ["path"],
        },
    )

    def execute(self, call: ToolCall) -> ToolResult:
        raise NotImplementedError
