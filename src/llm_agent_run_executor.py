from __future__ import annotations

from pathlib import Path

from src.config.settings import Settings
from src.context_builder import RunContextBuilder
from src.domain.tools.tool_definition import ToolDefinition
from src.executor_factory import create_tool_executor
from src.llm.base import LLMProvider
from src.llm.types import (
    LLMMessage,
    LLMRequest,
)
from src.llm_executor import LLMRunExecutor, LLMRunResult
from src.models import (
    RunExecutionContext,
    RunExecutionResult,
)
from src.repositories import AgentRepository, RunRepository
from src.run_events import JsonlRunEventSink


class LLMAgentRunExecutor:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        settings: Settings,
        agent_repository: AgentRepository,
        run_repository: RunRepository,
        project_root: Path,
    ) -> None:
        self._provider = provider
        self._settings = settings
        self._agent_repository = agent_repository
        self._run_repository = run_repository
        self._project_root = project_root

    def execute(
        self,
        context: RunExecutionContext,
    ) -> RunExecutionResult:
        agent_directory = self._agent_repository.get_agent_dir(
            context.agent.id
        )

        repository_root = self._resolve_repository_root(context)

        tool_executor = create_tool_executor(
            repository_root=repository_root,
            agent_directory=agent_directory,
        )

        events_path = self._run_repository.get_events_file(
            context.task.id,
            context.run.id,
        )

        event_sink = JsonlRunEventSink(
            events_path,
            truncate_existing=True,
        )

        llm_executor = LLMRunExecutor(
            provider=self._provider,
            tool_executor=tool_executor,
            max_tool_rounds=(
                self._settings.llm_max_tool_rounds
            ),
            max_total_tokens=(
                self._settings.llm_max_total_tokens
            ),
            event_sink=event_sink,
            debug_log_full_output=(
                self._settings.debug_log_full_output
            ),
        )

        request = self._build_request(
            context=context,
            tools=tool_executor.get_definitions(),
        )

        run_result = llm_executor.execute(request)

        return RunExecutionResult(
            output_markdown=self._build_output(
                context=context,
                run_result=run_result,
            ),
            summary_markdown=self._build_summary(
                context=context,
                run_result=run_result,
            ),
            metadata={
                "llm_rounds": run_result.llm_rounds,
                "tool_rounds": run_result.tool_rounds,
                "tool_calls": run_result.tool_calls,
                "total_input_tokens": run_result.total_input_tokens,
                "total_output_tokens": run_result.total_output_tokens,
            },
        )

    def _resolve_repository_root(
        self,
        context: RunExecutionContext,
    ) -> Path:
        return self._project_root

    def _resolve_model(
        self,
        context: RunExecutionContext,
    ) -> str:
        return (
            context.agent.default_model
            if context.agent.default_model
            != "claude-model-placeholder"
            else self._settings.anthropic_model
        )

    def _build_request(
        self,
        *,
        context: RunExecutionContext,
        tools: list[ToolDefinition],
    ) -> LLMRequest:
        model = self._resolve_model(context)

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
                self._settings.llm_max_tokens,
            ),
            tools=tools,
        )

    def _build_output(
        self,
        *,
        context: RunExecutionContext,
        run_result: LLMRunResult,
    ) -> str:
        return (
            "# Run Output\n\n"
            f"- Task ID: `{context.task.id}`\n"
            f"- Run ID: `{context.run.id}`\n"
            f"- Agent ID: `{context.agent.id}`\n"
            f"- Provider: `{self._provider.provider_name}`\n"
            f"- Model: `{self._resolve_model(context)}`\n"
            f"- Input tokens: `{run_result.total_input_tokens}`\n"
            f"- Output tokens: `{run_result.total_output_tokens}`\n\n"
            "## Agent Response\n\n"
            f"{run_result.final_response.text.strip()}\n"
        )

    def _build_summary(
        self,
        *,
        context: RunExecutionContext,
        run_result: LLMRunResult,
    ) -> str:
        total_tokens = (
            run_result.total_input_tokens
            + run_result.total_output_tokens
        )

        return (
            "# Run Summary\n\n"
            f"- Task ID: `{context.task.id}`\n"
            f"- Run ID: `{context.run.id}`\n"
            f"- Agent ID: `{context.agent.id}`\n"
            "- Status: `completed`\n"
            f"- Provider: `{self._provider.provider_name}`\n"
            f"- Model: `{self._resolve_model(context)}`\n"
            f"- Input tokens: `{run_result.total_input_tokens}`\n"
            f"- Output tokens: `{run_result.total_output_tokens}`\n"
            f"- Total tokens: `{total_tokens}`\n"
            f"- LLM rounds: `{run_result.llm_rounds}`\n"
            f"- Tool rounds: `{run_result.tool_rounds}`\n"
            f"- Tool calls: `{run_result.tool_calls}`\n"
            "- Summary: The run was executed using an "
            "LLM-backed executor with tool-calling support.\n"
            "- Remaining work: A management agent should "
            "later convert this run into structured task "
            "memory updates.\n"
        )
