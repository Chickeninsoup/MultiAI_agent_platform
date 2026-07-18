from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult


class ListFilesTool:
    """Lists files within an allowed directory."""

    definition = ToolDefinition(
        name="list_files",
        description="List files within an allowed directory.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list.",
                },
            },
            "required": ["path"],
        },
    )

    def execute(self, call: ToolCall) -> ToolResult:
        raise NotImplementedError
