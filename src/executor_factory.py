from src.config.settings import Settings
from src.execution import RunExecutor
from src.repositories import AgentRepository
from src.simulated_executor import SimulatedRunExecutor

from pathlib import Path

from src.services.tools.handlers.git_diff_tool import GitDiffTool
from src.services.tools.handlers.git_status_tool import GitStatusTool
from src.services.tools.handlers.list_files_tool import ListFilesTool
from src.services.tools.handlers.read_file_tool import ReadFileTool
from src.services.tools.tool_executor import ToolExecutor
from src.services.tools.tool_policy import load_tool_policy

def create_run_executor(
    settings: Settings,
    *,
    project_root: Path,
    agent_repository: AgentRepository,
) -> RunExecutor:
    """Create a run executor from application settings."""

    if settings.execution_mode == "simulated":
        return SimulatedRunExecutor()

    if settings.execution_mode == "llm":
        return _create_llm_executor(
            settings,
            project_root=project_root,
            agent_repository=agent_repository,
        )

    raise ValueError(
        f"Unsupported execution mode: "
        f"{settings.execution_mode}"
    )


def _create_llm_executor(
    settings: Settings,
    *,
    project_root: Path,
    agent_repository: AgentRepository,
) -> RunExecutor:
    from src.llm.anthropic_provider import AnthropicProvider
    from src.llm_executor import LLMAgentRunExecutor

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

    provider = AnthropicProvider(
        api_key=api_key,
        timeout_seconds=settings.llm_timeout_seconds,
        max_retries=settings.llm_max_retries,
    )

    return LLMAgentRunExecutor(
        provider=provider,
        agent_repository=agent_repository,
        repository_root=project_root,
        tool_executor_factory=(
            lambda repository_root, agent_directory: (
                create_tool_executor(
                    repository_root=repository_root,
                    agent_directory=agent_directory,
                )
            )
        ),
        default_model=settings.anthropic_model,
        default_max_tokens=settings.llm_max_tokens,
        max_tool_rounds=settings.llm_max_tool_rounds,
        max_total_tokens=settings.llm_max_total_tokens,
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