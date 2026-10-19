from __future__ import annotations

from pathlib import Path

from src.approval_application_outcome import ApprovalApplicationOutcome
from src.approval_pause import ApprovalPause
from src.approval_rule import ApprovalRule
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
from src.run_approval_rule_snapshot import (
    save as save_approval_rule_snapshot,
)
from src.run_continuation_checkpoint import RunContinuationCheckpoint
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)
from src.run_events import JsonlRunEventSink
from src.tool_approval_gate import ToolApprovalGate


class LLMAgentRunExecutor:
    def __init__(
        self,
        *,
        provider: LLMProvider,
        settings: Settings,
        agent_repository: AgentRepository,
        run_repository: RunRepository,
        project_root: Path,
        approval_gate: ToolApprovalGate | None = None,
        continuation_checkpoint_repository: (
            RunContinuationCheckpointRepository | None
        ) = None,
        approval_rules: list[ApprovalRule] | None = None,
    ) -> None:
        self._provider = provider
        self._settings = settings
        self._agent_repository = agent_repository
        self._run_repository = run_repository
        self._project_root = project_root
        # None by default - "no approval gate configured" (5E-5D-4B).
        # Production wiring (a real ToolApprovalGate backed by a
        # persistent ApprovalStore and a real configured rule set) is
        # built by src/run_service_composition.py (5E-5D-6D) - every
        # existing call site that constructs this class without
        # approval_gate keeps its exact prior (ungated) behavior.
        self._approval_gate = approval_gate
        # Same optional/None-by-default treatment as approval_gate
        # (5E-5D-4C) - not built here, injected already-constructed
        # by whoever composes this class, so this class never
        # constructs a repository or filesystem path itself. If
        # approval_gate is set but this is left None, LLMRunExecutor's
        # own constructor (built fresh per execute() call, below)
        # raises immediately - not re-validated a second time here.
        self._continuation_checkpoint_repository = (
            continuation_checkpoint_repository
        )
        # The exact ApprovalRules the caller's live approval-policy
        # configuration resolved to for this executor instance
        # (5E-5D-6D) - None means "do not persist a snapshot at all"
        # (every existing test/caller that never passes this), not
        # "persist an empty one". Persisted once, at the top of
        # execute() (a *fresh* Run start), not on resume_after_approval()
        # (a continuation, which must read this Run's own already-
        # persisted snapshot instead of writing a new one - see
        # src/run_service_composition.py). Plays no role in any
        # approval *decision* here - approval_gate alone already fully
        # encodes that; this field exists only so a later continuation
        # can reconstruct the identical policy without re-reading a
        # live config file that may have since changed or vanished.
        self._approval_rules = approval_rules

    def execute(
        self,
        context: RunExecutionContext,
    ) -> RunExecutionResult:
        if self._approval_rules is not None:
            # Written once, at the top of a fresh Run's execute() -
            # never on resume_after_approval() (5E-5D-6D). This is the
            # one durable record a later resume_after_approval() reads
            # back (via src/run_service_composition.py) instead of
            # re-reading the live approval-policy config file, which
            # may have since changed or been deleted.
            save_approval_rule_snapshot(
                self._run_repository.get_run_dir(
                    context.task.id, context.run.id
                ),
                self._approval_rules,
            )

        agent_directory = self._agent_repository.get_agent_dir(
            context.agent.id
        )

        repository_root = self._resolve_repository_root(context)

        tool_executor = create_tool_executor(
            repository_root=repository_root,
            agent_directory=agent_directory,
            test_policy_path=(
                self._project_root
                / self._settings.test_policy_path
            ),
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
            approval_gate=self._approval_gate,
            run_id=context.run.id,
            task_id=context.task.id,
            continuation_checkpoint_repository=(
                self._continuation_checkpoint_repository
            ),
        )

        request = self._build_request(
            context=context,
            tools=tool_executor.get_definitions(),
        )

        run_result = llm_executor.execute(request)

        if run_result.waiting_for_approval is not None:
            return self._build_waiting_result(
                context=context, run_result=run_result
            )

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

    def resume_after_approval(
        self,
        context: RunExecutionContext,
        checkpoint: RunContinuationCheckpoint,
        outcome: ApprovalApplicationOutcome,
    ) -> RunExecutionResult:
        """Finishes the interrupted tool round checkpoint describes
        and continues the same Run's LLM loop (5E-5D-6C) - built the
        same way execute() builds a fresh LLMRunExecutor (same
        provider/settings/tool policy derivation), the one difference
        being resume_from_checkpoint() instead of execute() on it.
        No second execution loop: LLMRunExecutor.resume_from_checkpoint()
        is the identical tool-call/LLM loop execute() already drives.

        Refuses outright if approval gating is not actually configured
        on this executor (5E-5D-6C: "do not silently fall back to an
        executor with approval gating disabled") - the same
        precondition LLMRunExecutor's own constructor already enforces
        whenever approval_gate is not None, checked again here before
        even that constructor runs, so a caller gets a clear,
        continuation-specific error rather than whatever
        ValueError message LLMRunExecutor's constructor happens to
        raise.
        """

        if (
            self._approval_gate is None
            or self._continuation_checkpoint_repository is None
        ):
            raise ValueError(
                "LLMAgentRunExecutor.resume_after_approval() requires "
                "approval_gate and continuation_checkpoint_repository "
                "to be configured - refusing to continue with "
                "approval gating disabled"
            )

        agent_directory = self._agent_repository.get_agent_dir(
            context.agent.id
        )

        repository_root = self._resolve_repository_root(context)

        tool_executor = create_tool_executor(
            repository_root=repository_root,
            agent_directory=agent_directory,
            test_policy_path=(
                self._project_root
                / self._settings.test_policy_path
            ),
        )

        events_path = self._run_repository.get_events_file(
            context.task.id,
            context.run.id,
        )

        # Append, never truncate (5E-5D-6C) - this continuation shares
        # the ORIGINAL Run's own event log, not a new one, so a later
        # ChangeSnapshot (built by reading this same events.jsonl in
        # full) naturally covers file_mutation events from before the
        # pause and after the resume alike. truncate_existing=True here
        # would silently discard the pre-pause history and make a
        # later review present only the post-resume slice as if it
        # were the whole Run.
        event_sink = JsonlRunEventSink(
            events_path,
            truncate_existing=False,
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
            approval_gate=self._approval_gate,
            run_id=context.run.id,
            task_id=context.task.id,
            continuation_checkpoint_repository=(
                self._continuation_checkpoint_repository
            ),
        )

        request_template = self._build_request(
            context=context,
            tools=tool_executor.get_definitions(),
        )

        run_result = llm_executor.resume_from_checkpoint(
            request_template, checkpoint, outcome
        )

        if run_result.cancelled:
            return self._build_cancelled_result(
                context=context, run_result=run_result
            )

        if run_result.waiting_for_approval is not None:
            return self._build_waiting_result(
                context=context, run_result=run_result
            )

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

    def _build_cancelled_result(
        self,
        *,
        context: RunExecutionContext,
        run_result: LLMRunResult,
    ) -> RunExecutionResult:
        return RunExecutionResult(
            output_markdown=self._build_cancelled_output(
                context=context, run_result=run_result
            ),
            summary_markdown=self._build_cancelled_summary(
                context=context, run_result=run_result
            ),
            metadata={
                "llm_rounds": run_result.llm_rounds,
                "tool_rounds": run_result.tool_rounds,
                "tool_calls": run_result.tool_calls,
                "total_input_tokens": run_result.total_input_tokens,
                "total_output_tokens": run_result.total_output_tokens,
                "cancelled": True,
            },
        )

    def _build_cancelled_output(
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
            f"- Input tokens: `{run_result.total_input_tokens}`\n"
            f"- Output tokens: `{run_result.total_output_tokens}`\n\n"
            "## Cancelled\n\n"
            "A human cancelled the pending tool call this run was "
            "waiting on approval for. No further tool calls or model "
            "requests were made. Effects of any tool calls that "
            "already ran before the pause are preserved.\n"
        )

    def _build_cancelled_summary(
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
            "- Status: `cancelled`\n"
            f"- Input tokens: `{run_result.total_input_tokens}`\n"
            f"- Output tokens: `{run_result.total_output_tokens}`\n"
            f"- Total tokens: `{total_tokens}`\n"
            f"- LLM rounds: `{run_result.llm_rounds}`\n"
            f"- Tool rounds: `{run_result.tool_rounds}`\n"
            f"- Tool calls: `{run_result.tool_calls}`\n"
            "- Summary: A human cancelled the pending tool call this "
            "run was waiting for approval on. Execution stopped "
            "there.\n"
        )

    def _build_waiting_result(
        self,
        *,
        context: RunExecutionContext,
        run_result: LLMRunResult,
    ) -> RunExecutionResult:
        pause = run_result.waiting_for_approval
        assert pause is not None

        return RunExecutionResult(
            output_markdown=self._build_waiting_output(
                context=context, run_result=run_result, pause=pause
            ),
            summary_markdown=self._build_waiting_summary(
                context=context, run_result=run_result, pause=pause
            ),
            metadata={
                "llm_rounds": run_result.llm_rounds,
                "tool_rounds": run_result.tool_rounds,
                "tool_calls": run_result.tool_calls,
                "total_input_tokens": run_result.total_input_tokens,
                "total_output_tokens": run_result.total_output_tokens,
                "waiting_for_approval": True,
                "approval_id": pause.approval_id,
                "tool_call_id": pause.tool_call_id,
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

    def _build_waiting_output(
        self,
        *,
        context: RunExecutionContext,
        run_result: LLMRunResult,
        pause: ApprovalPause,
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
            "## Waiting For Approval\n\n"
            f"- Approval ID: `{pause.approval_id}`\n"
            f"- Tool call ID: `{pause.tool_call_id}`\n\n"
            "Execution paused before running a tool call that "
            "requires human approval. No further tool calls or "
            "model requests were made after this point.\n"
        )

    def _build_waiting_summary(
        self,
        *,
        context: RunExecutionContext,
        run_result: LLMRunResult,
        pause: ApprovalPause,
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
            "- Status: `waiting_for_approval`\n"
            f"- Approval ID: `{pause.approval_id}`\n"
            f"- Provider: `{self._provider.provider_name}`\n"
            f"- Model: `{self._resolve_model(context)}`\n"
            f"- Input tokens: `{run_result.total_input_tokens}`\n"
            f"- Output tokens: `{run_result.total_output_tokens}`\n"
            f"- Total tokens: `{total_tokens}`\n"
            f"- LLM rounds: `{run_result.llm_rounds}`\n"
            f"- Tool rounds: `{run_result.tool_rounds}`\n"
            f"- Tool calls: `{run_result.tool_calls}`\n"
            "- Summary: Execution paused before a tool call that "
            "requires human approval. A human must approve, "
            "reject, modify, or cancel it before this run can "
            "continue.\n"
        )
