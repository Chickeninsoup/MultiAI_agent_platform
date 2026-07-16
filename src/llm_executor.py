from src.execution import (
    RunExecutionContext,
    RunExecutionResult,
)
from src.llm.base import LLMProvider
from src.llm.types import LLMMessage, LLMRequest


class LLMRunExecutor:
    """Execute a run through a language model provider."""

    def __init__(
        self,
        provider: LLMProvider,
        *,
        default_model: str,
        default_max_tokens: int,
    ) -> None:
        if not default_model.strip():
            raise ValueError(
                "Default model must not be empty"
            )

        if default_max_tokens <= 0:
            raise ValueError(
                "Default max tokens must be positive"
            )

        self._provider = provider
        self._default_model = default_model
        self._default_max_tokens = default_max_tokens

    def execute(
        self,
        context: RunExecutionContext,
    ) -> RunExecutionResult:
        request = self._build_request(context)
        response = self._provider.generate(request)

        output = self._build_output(
            context=context,
            response_text=response.text,
            provider=response.provider,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        summary = self._build_summary(
            context=context,
            provider=response.provider,
            model=response.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        return RunExecutionResult(
            output=output,
            summary=summary,
        )

    def _build_request(
        self,
        context: RunExecutionContext,
    ) -> LLMRequest:
        model = (
            context.agent.default_model
            if context.agent.default_model
            != "claude-model-placeholder"
            else self._default_model
        )

        system_prompt = (
            "You are executing a task as an AI agent.\n\n"
            f"Agent ID: {context.agent.id}\n"
            f"Agent name: {context.agent.name}\n"
            f"Agent role: {context.agent.role}\n"
            f"Agent description: {context.agent.description}\n\n"
            "Complete the run based on the supplied task "
            "and run input."
        )

        user_content = (
            f"Task ID: {context.task.id}\n"
            f"Task title: {context.task.title}\n"
            f"Task description: {context.task.description}\n\n"
            "Completion criteria:\n"
            + "\n".join(
                f"- {criterion}"
                for criterion
                in context.task.completion_criteria
            )
            + "\n\nRun input:\n"
            + context.run_input
        )

        return LLMRequest(
            system_prompt=system_prompt,
            messages=[
                LLMMessage(
                    role="user",
                    content=user_content,
                )
            ],
            model=model,
            max_tokens=min(
                context.agent.limits.max_output_tokens,
                self._default_max_tokens,
            ),
            metadata={
                "task_id": context.task.id,
                "run_id": context.run.id,
                "agent_id": context.agent.id,
            },
        )

    @staticmethod
    def _build_output(
        context: RunExecutionContext,
        response_text: str,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> str:
        return (
            "# Run Output\n\n"
            f"- Task ID: `{context.task.id}`\n"
            f"- Run ID: `{context.run.id}`\n"
            f"- Agent ID: `{context.agent.id}`\n"
            f"- Provider: `{provider}`\n"
            f"- Model: `{model}`\n"
            f"- Input tokens: `{input_tokens}`\n"
            f"- Output tokens: `{output_tokens}`\n\n"
            "## Agent Response\n\n"
            f"{response_text.strip()}\n"
        )

    @staticmethod
    def _build_summary(
        context: RunExecutionContext,
        provider: str,
        model: str,
        input_tokens: int,
        output_tokens: int,
    ) -> str:
        return (
            "# Run Summary\n\n"
            f"- Task ID: `{context.task.id}`\n"
            f"- Run ID: `{context.run.id}`\n"
            f"- Agent ID: `{context.agent.id}`\n"
            "- Status: `completed`\n"
            f"- Provider: `{provider}`\n"
            f"- Model: `{model}`\n"
            f"- Input tokens: `{input_tokens}`\n"
            f"- Output tokens: `{output_tokens}`\n"
            "- Summary: The run was executed using an "
            "LLM-backed executor.\n"
            "- Remaining work: A management agent should "
            "later convert this run into structured task "
            "memory updates.\n"
        )

