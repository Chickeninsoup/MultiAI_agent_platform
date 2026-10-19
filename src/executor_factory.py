from pathlib import Path

from src.approval_rule import ApprovalRule
from src.config.settings import Settings
from src.execution import RunExecutor
from src.llm.base import LLMProvider
from src.llm.types import LLMRequest, LLMResponse
from src.repositories import AgentRepository, RunRepository
from src.run_continuation_checkpoint_repository import (
    RunContinuationCheckpointRepository,
)
from src.simulated_executor import SimulatedRunExecutor
from src.tool_approval_gate import ToolApprovalGate

from src.services.tools.handlers.git_diff_tool import GitDiffTool
from src.services.tools.handlers.git_status_tool import GitStatusTool
from src.services.tools.handlers.list_files_tool import ListFilesTool
from src.services.tools.handlers.patch_file_tool import PatchFileTool
from src.services.tools.handlers.read_file_tool import ReadFileTool
from src.services.tools.handlers.run_test_tool import RunTestTool
from src.services.tools.handlers.write_file_tool import WriteFileTool
from src.services.tools.test_policy import TestPolicy
from src.services.tools.test_runner import TestRunner
from src.services.tools.tool_executor import ToolExecutor
from src.services.tools.tool_policy import load_tool_policy

# The exact tool names create_tool_executor() below registers (5E-5D-
# 6D) - kept as one explicit constant rather than derived from the
# handler list at call time, so approval-policy configuration
# validation (src/approval_policy_config.py: "unknown tool names must
# not silently become an empty policy") and the safe previewer
# (src/schema_aware_tool_input_previewer.py) can both validate/preview
# against the real registry without constructing a ToolExecutor (which
# needs a real tool-policy.json/test-policy.json already loaded) just
# to ask "what tool names exist". Must be kept in sync with
# create_tool_executor()'s handler list by hand - the same manual-sync
# tradeoff _SAFE_FIELDS_BY_TOOL already documents, for the same reason
# (a tool's registration and whether it is safe to preview/approve-gate
# are both judgment calls, not something to infer automatically).
KNOWN_TOOL_NAMES: frozenset[str] = frozenset(
    {
        "list_files",
        "read_file",
        "git_status",
        "git_diff",
        "write_file",
        "patch_file",
        "run_test",
    }
)


def create_run_executor(
    *,
    settings: Settings,
    agent_repository: AgentRepository,
    run_repository: RunRepository,
    project_root: Path,
    approval_gate: ToolApprovalGate | None = None,
    continuation_checkpoint_repository: (
        RunContinuationCheckpointRepository | None
    ) = None,
    approval_rules: list[ApprovalRule] | None = None,
) -> RunExecutor:
    """Create a run executor from application settings.

    approval_gate/continuation_checkpoint_repository/approval_rules
    (5E-5D-6D) are all optional and all default to the exact prior
    behavior (no approval gating at all) when omitted - the same
    "None means not configured" convention LLMAgentRunExecutor/
    LLMRunExecutor already established for these two collaborators
    (5E-5D-4B/4C). approval_rules is forwarded only for
    LLMAgentRunExecutor to persist as this Run's durable
    approval-rule snapshot at execute()-start - it plays no role in
    any approval *decision*, which approval_gate alone already fully
    encodes.

    A configured approval_gate with execution_mode == "simulated" is
    rejected outright, not silently ignored - SimulatedRunExecutor has
    no concept of a tool-call loop to gate at all, so silently
    dropping the gate would make a configured approval policy quietly
    do nothing for every Run run in simulated mode.
    """

    if approval_gate is not None and settings.execution_mode != "llm":
        raise ValueError(
            "An approval_gate is configured, but execution_mode "
            f"{settings.execution_mode!r} does not support approval "
            "gating (only 'llm' does) - refusing to silently ignore "
            "the configured policy"
        )

    if settings.execution_mode == "simulated":
        return SimulatedRunExecutor()

    if settings.execution_mode == "llm":
        return _create_llm_executor(
            settings,
            agent_repository=agent_repository,
            run_repository=run_repository,
            project_root=project_root,
            approval_gate=approval_gate,
            continuation_checkpoint_repository=(
                continuation_checkpoint_repository
            ),
            approval_rules=approval_rules,
        )

    raise ValueError(
        f"Unsupported execution mode: "
        f"{settings.execution_mode}"
    )


def _create_llm_executor(
    settings: Settings,
    *,
    agent_repository: AgentRepository,
    run_repository: RunRepository,
    project_root: Path,
    approval_gate: ToolApprovalGate | None = None,
    continuation_checkpoint_repository: (
        RunContinuationCheckpointRepository | None
    ) = None,
    approval_rules: list[ApprovalRule] | None = None,
) -> RunExecutor:
    from src.llm_agent_run_executor import LLMAgentRunExecutor

    provider = _LazyLLMProvider(settings)

    return LLMAgentRunExecutor(
        provider=provider,
        settings=settings,
        agent_repository=agent_repository,
        run_repository=run_repository,
        project_root=project_root,
        approval_gate=approval_gate,
        continuation_checkpoint_repository=(
            continuation_checkpoint_repository
        ),
        approval_rules=approval_rules,
    )


class _LazyLLMProvider:
    """Defers constructing the real provider - and validating its
    required credentials - until .complete() is actually invoked for
    the first time (5E-5D-6D).

    Without this, building a RunExecutor (and therefore a RunService)
    at CLI composition time would itself require ANTHROPIC_API_KEY to
    already be set, for *every* command - including ones that never
    make a provider call at all: help, inspection
    (list-tool-approvals/show-tool-approval), decision recording
    (approve/reject/modify/cancel-tool-call), a cached
    resume-after-approval replay (RunService.resume_after_approval()'s
    own COMPLETED-attempt short-circuit never touches the executor),
    and CANCEL (LLMRunExecutor.resume_from_checkpoint()'s own
    CANCEL_RUN branch never calls self._provider.complete() either).
    Wrapping the real provider lazily means none of those paths is
    ever blocked by a missing or invalid API key - only a path that
    genuinely reaches a fresh LLM round does.

    provider_name is answered without constructing the real provider
    at all (it is a fixed, settings-derived string, identical to what
    the real AnthropicProvider.provider_name already always returns) -
    LLMAgentRunExecutor's own output/summary builders read this after
    a Run already produced at least one real response (so the real
    provider is already constructed by then) or not at all (CANCEL
    builds no such output), but there is no reason to force
    construction just to answer this one static fact either way.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._real: LLMProvider | None = None

    @property
    def provider_name(self) -> str:
        return self._settings.llm_provider

    def complete(self, request: LLMRequest) -> LLMResponse:
        if self._real is None:
            self._real = create_llm_provider(self._settings)

        return self._real.complete(request)


def create_llm_provider(settings: Settings) -> LLMProvider:
    from src.llm.anthropic_provider import AnthropicProvider

    if settings.llm_provider != "anthropic":
        raise ValueError(
            f"Unsupported LLM provider: "
            f"{settings.llm_provider}"
        )

    api_key = settings.anthropic_api_key

    if not api_key:
        raise ValueError(
            "Anthropic API key is required "
            "for LLM execution"
        )

    return AnthropicProvider(
        api_key=api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )


def create_tool_executor(
    *,
    repository_root: Path,
    agent_directory: Path,
    test_policy_path: Path,
    default_max_output_chars: int = 100_000,
    default_max_write_bytes: int = 100_000,
) -> ToolExecutor:
    policy_path = agent_directory / "tool-policy.json"
    tool_policy = load_tool_policy(policy_path)
    test_policy = TestPolicy.load(test_policy_path)

    return ToolExecutor(
        repository_root=repository_root,
        handlers=[
            ListFilesTool(),
            ReadFileTool(),
            GitStatusTool(),
            GitDiffTool(),
            WriteFileTool(
                max_write_bytes=tool_policy.get_max_write_bytes(
                    "write_file",
                    default_max_write_bytes,
                ),
            ),
            PatchFileTool(),
            RunTestTool(
                test_policy=test_policy,
                test_runner=TestRunner(),
            ),
        ],
        tool_policy=tool_policy,
        max_output_chars=default_max_output_chars,
    )