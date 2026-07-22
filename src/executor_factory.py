from pathlib import Path

from src.config.settings import Settings
from src.execution import RunExecutor
from src.llm.base import LLMProvider
from src.repositories import AgentRepository, RunRepository
from src.simulated_executor import SimulatedRunExecutor

from src.services.tools.handlers.git_diff_tool import GitDiffTool
from src.services.tools.handlers.git_status_tool import GitStatusTool
from src.services.tools.handlers.list_files_tool import ListFilesTool
from src.services.tools.handlers.read_file_tool import ReadFileTool
from src.services.tools.tool_executor import ToolExecutor
from src.services.tools.tool_policy import load_tool_policy


def create_run_executor(
    *,
    settings: Settings,
    agent_repository: AgentRepository,
    run_repository: RunRepository,
    project_root: Path,
) -> RunExecutor:
    """Create a run executor from application settings."""

    if settings.execution_mode == "simulated":
        return SimulatedRunExecutor()

    if settings.execution_mode == "llm":
        return _create_llm_executor(
            settings,
            agent_repository=agent_repository,
            run_repository=run_repository,
            project_root=project_root,
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
) -> RunExecutor:
    from src.llm_agent_run_executor import LLMAgentRunExecutor

    provider = create_llm_provider(settings)

    return LLMAgentRunExecutor(
        provider=provider,
        settings=settings,
        agent_repository=agent_repository,
        run_repository=run_repository,
        project_root=project_root,
    )


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
    default_max_output_chars: int = 100_000,
) -> ToolExecutor:
    policy_path = agent_directory / "tool-policy.json"
    tool_policy = load_tool_policy(policy_path)

    return ToolExecutor(
        repository_root=repository_root,
        handlers=[
            ListFilesTool(),
            ReadFileTool(),
            GitStatusTool(),
            GitDiffTool(),
        ],
        tool_policy=tool_policy,
        max_output_chars=default_max_output_chars,
    )