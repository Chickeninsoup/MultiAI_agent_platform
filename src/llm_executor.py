from src.execution import (
    RunExecutionContext,
    RunExecutionResult,
)
from src.llm.base import LLMProvider
from src.llm.types import LLMMessage, LLMRequest

from src.context_builder import RunContextBuilder

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
            
        if response.stop_reason == "max_tokens":
            raise RuntimeError(
                "LLM response reached the maximum token "
                "limit before completing. Increase the "
                "output budget or reduce the requested "
                "scope."
            )

        if not response.text.strip():
            raise RuntimeError(
                "LLM provider returned no text content. "
                f"Stop reason: {response.stop_reason}"
            )
            
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

        platform_instructions = (
            "You are executing one run inside an AI agent "
            "platform.\n\n"
            "Important execution rules:\n"
            "1. You do not currently have interactive tools.\n"
            "2. Do not claim to read, list, modify, or inspect "
            "anything that is not included in the supplied "
            "context.\n"
            "3. Do not emit simulated tool calls.\n"
            "4. Base all factual conclusions about the project "
            "only on the supplied project snapshot.\n"
            "5. Complete the requested work in this response. "
            "Do not stop after announcing a plan.\n"
            "6. Clearly distinguish observed facts from "
            "recommendations or assumptions.\n"
            "7.By default, Chinese should be used in the responses, "
            "except when English is required when referring to proper nouns "
            "or when the user explicitly requests the use of other languages\n"
        )

        system_prompt_parts = [
            platform_instructions,
            (
                "\nAgent identity:\n"
                f"- ID: {context.agent.id}\n"
                f"- Name: {context.agent.name}\n"
                f"- Role: {context.agent.role}\n"
                f"- Description: "
                f"{context.agent.description}\n"
            ),
        ]

        if context.agent_system_prompt.strip():
            system_prompt_parts.extend(
                [
                    "\nAgent-specific system prompt:\n",
                    context.agent_system_prompt.strip(),
                ]
            )

        tool_policy_text = (
            RunContextBuilder.format_tool_policy(
                context.tool_policy
            )
        )

        completion_criteria = "\n".join(
            f"- {criterion}"
            for criterion in context.task.completion_criteria
        )

        background = (
            context.task_background.strip()
            or "No task background has been recorded."
        )

        user_content = (
            f"# Task\n\n"
            f"Task ID: {context.task.id}\n"
            f"Title: {context.task.title}\n"
            f"Description: {context.task.description}\n\n"
            f"## Completion Criteria\n\n"
            f"{completion_criteria}\n\n"
            f"## Shared Task Background\n\n"
            f"{background}\n\n"
            f"## Agent Tool Policy\n\n"
            f"```json\n{tool_policy_text}\n```\n\n"
            f"## Current Run Input\n\n"
            f"{context.run_input.strip()}\n\n"
            f"{context.project_snapshot}\n\n"
            "Produce the complete requested result now."
        )

        return LLMRequest(
            system_prompt="\n".join(
                system_prompt_parts
            ),
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

