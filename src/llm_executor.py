from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from typing import Callable

from src.context_builder import RunContextBuilder
from src.domain.tools.tool_call import ToolCall
from src.execution import RunExecutionContext, RunExecutionResult
from src.llm.base import LLMProvider
from src.llm.types import (
    LLMMessage,
    LLMRequest,
    LLMResponse,
)
from src.repositories import AgentRepository
from src.services.tools.tool_executor import ToolExecutor


class LLMRunLimitError(RuntimeError):
    pass


class LLMRunExecutor:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        tool_executor: ToolExecutor,
        max_tool_rounds: int = 8,
        max_total_tokens: int = 100_000,
    ) -> None:
        self._provider = provider
        self._tool_executor = tool_executor
        self._max_tool_rounds = max_tool_rounds
        self._max_total_tokens = max_total_tokens

    def execute(
        self,
        request: LLMRequest,
    ) -> LLMResponse:
        messages = list(request.messages)
        total_tokens = 0
        tool_rounds = 0

        while True:
            current_request = replace(
                request,
                messages=list(messages),
                tools=self._tool_executor.get_definitions(),
            )

            response = self._provider.complete(current_request)

            total_tokens += (
                response.usage.input_tokens
                + response.usage.output_tokens
            )

            if total_tokens > self._max_total_tokens:
                raise LLMRunLimitError(
                    "Maximum total token limit exceeded."
                )

            messages.append(
                LLMMessage(
                    role="assistant",
                    content=response.to_message_content(),
                )
            )

            if (
                response.stop_reason == "tool_use"
                and not response.has_tool_calls
            ):
                raise RuntimeError(
                    "Provider returned tool_use stop reason "
                    "without tool calls."
                )

            if not response.has_tool_calls:
                return response

            tool_rounds += 1

            if tool_rounds > self._max_tool_rounds:
                raise LLMRunLimitError(
                    "Maximum tool rounds exceeded."
                )

            tool_result_blocks: list[dict[str, object]] = []

            for tool_use in response.tool_calls:
                result = self._tool_executor.execute(
                    ToolCall(
                        id=tool_use.id,
                        name=tool_use.name,
                        input=tool_use.input,
                    )
                )

                tool_result_blocks.append(
                    result.to_message_block()
                )

            messages.append(
                LLMMessage(
                    role="user",
                    content=tool_result_blocks,
                )
            )


class LLMAgentRunExecutor:
    """Run a task through the LLM tool-calling loop.

    Adapts RunExecutionContext/RunExecutionResult (what RunService
    speaks) to LLMRequest/LLMResponse (what LLMRunExecutor speaks),
    building a fresh ToolExecutor per run since tool policy is
    agent-specific.
    """

    def __init__(
        self,
        *,
        provider: LLMProvider,
        agent_repository: AgentRepository,
        repository_root: Path,
        tool_executor_factory: Callable[
            [Path, Path], ToolExecutor
        ],
        default_model: str,
        default_max_tokens: int,
        max_tool_rounds: int = 8,
        max_total_tokens: int = 100_000,
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
        self._agent_repository = agent_repository
        self._repository_root = repository_root
        self._tool_executor_factory = tool_executor_factory
        self._default_model = default_model
        self._default_max_tokens = default_max_tokens
        self._max_tool_rounds = max_tool_rounds
        self._max_total_tokens = max_total_tokens

    def execute(
        self,
        context: RunExecutionContext,
    ) -> RunExecutionResult:
        request = self._build_request(context)

        tool_executor = self._tool_executor_factory(
            self._repository_root,
            self._agent_repository.get_agent_dir(
                context.agent.id
            ),
        )

        runner = LLMRunExecutor(
            provider=self._provider,
            tool_executor=tool_executor,
            max_tool_rounds=self._max_tool_rounds,
            max_total_tokens=self._max_total_tokens,
        )

        response = runner.execute(request)

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
            provider=self._provider.provider_name,
            model=request.model,
            input_tokens=response.usage.input_tokens,
            output_tokens=response.usage.output_tokens,
        )

        summary = self._build_summary(
            context=context,
            provider=self._provider.provider_name,
            model=request.model,
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
            "1. You have access to the tools declared for "
            "this request. Use them to inspect the "
            "repository when the supplied project snapshot "
            "is insufficient.\n"
            "2. Do not claim to have read, listed, modified, "
            "or inspected anything you have not actually "
            "retrieved through a tool call or the supplied "
            "context.\n"
            "3. Complete the requested work in this response. "
            "Do not stop after announcing a plan.\n"
            "4. Clearly distinguish observed facts (from the "
            "snapshot or tool results) from recommendations "
            "or assumptions.\n"
            "5. By default, Chinese should be used in the "
            "responses, except when English is required when "
            "referring to proper nouns or when the user "
            "explicitly requests the use of other languages\n"
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
            "LLM-backed executor with tool-calling support.\n"
            "- Remaining work: A management agent should "
            "later convert this run into structured task "
            "memory updates.\n"
        )