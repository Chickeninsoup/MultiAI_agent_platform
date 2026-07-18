from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult


class GitStatusTool:
    """Shows the working tree status of a git repository."""

    definition = ToolDefinition(
        name="git_status",
        description="Show the working tree status of a git repository.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Repository path to inspect.",
                },
            },
            "required": ["path"],
        },
    )

    def execute(self, call: ToolCall) -> ToolResult:
        raise NotImplementedError
