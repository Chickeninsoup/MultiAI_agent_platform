from src.config.settings import Settings
from src.execution import RunExecutor
from src.llm.anthropic_provider import AnthropicProvider
from src.llm_executor import LLMRunExecutor
from src.simulated_executor import SimulatedRunExecutor


def create_run_executor(
    settings: Settings,
) -> RunExecutor:
    """Create a run executor from application settings."""

    if settings.execution_mode == "simulated":
        return SimulatedRunExecutor()

    if settings.execution_mode == "llm":
        return _create_llm_executor(settings)

    raise ValueError(
        f"Unsupported execution mode: "
        f"{settings.execution_mode}"
    )


def _create_llm_executor(
    settings: Settings,
) -> RunExecutor:
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

    return LLMRunExecutor(
        provider=provider,
        default_model=settings.anthropic_model,
        default_max_tokens=settings.llm_max_tokens,
    )
