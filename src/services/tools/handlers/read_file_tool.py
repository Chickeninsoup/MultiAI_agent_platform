from src.domain.tools.tool_call import ToolCall
from src.domain.tools.tool_definition import ToolDefinition
from src.domain.tools.tool_result import ToolResult


class ReadFileTool:
    """Reads the contents of a file within an allowed directory."""

    definition = ToolDefinition(
        name="read_file",
        description="Read the contents of a file within an allowed directory.",
        input_schema={
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path to read.",
                },
            },
            "required": ["path"],
        },
    )

    def execute(self, call: ToolCall) -> ToolResult:
        raise NotImplementedError
