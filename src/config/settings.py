
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from dotenv import load_dotenv


ExecutionMode = Literal["simulated", "llm"]
LLMProviderName = Literal["anthropic"]


def _read_positive_int(
    variable_name: str,
    default: int,
) -> int:
    raw_value = os.getenv(variable_name)

    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(
            f"Environment variable {variable_name} "
            "must be an integer"
        ) from error

    if value <= 0:
        raise ValueError(
            f"Environment variable {variable_name} "
            "must be positive"
        )

    return value


def _read_non_negative_int(
    variable_name: str,
    default: int,
) -> int:
    raw_value = os.getenv(variable_name)

    if raw_value is None:
        return default

    try:
        value = int(raw_value)
    except ValueError as error:
        raise ValueError(
            f"Environment variable {variable_name} "
            "must be an integer"
        ) from error

    if value < 0:
        raise ValueError(
            f"Environment variable {variable_name} "
            "must not be negative"
        )

    return value


def _read_positive_float(
    variable_name: str,
    default: float,
) -> float:
    raw_value = os.getenv(variable_name)

    if raw_value is None:
        return default

    try:
        value = float(raw_value)
    except ValueError as error:
        raise ValueError(
            f"Environment variable {variable_name} "
            "must be a number"
        ) from error

    if value <= 0:
        raise ValueError(
            f"Environment variable {variable_name} "
            "must be positive"
        )

    return value


def _read_bool(
    variable_name: str,
    default: bool,
) -> bool:
    raw_value = os.getenv(variable_name)

    if raw_value is None:
        return default

    normalized = raw_value.strip().lower()

    if normalized in {"1", "true", "yes", "on"}:
        return True

    if normalized in {"0", "false", "no", "off"}:
        return False

    raise ValueError(
        f"Environment variable {variable_name} "
        "must be a boolean (true/false)"
    )


@dataclass(frozen=True)
class Settings:
    execution_mode: ExecutionMode
    llm_provider: LLMProviderName
    anthropic_api_key: str | None
    anthropic_model: str
    llm_timeout_seconds: float
    llm_max_retries: int
    llm_max_tokens: int
    llm_max_tool_rounds: int
    llm_max_total_tokens: int
    debug_log_full_output: bool
    test_policy_path: str
    approval_policy_path: str

    @classmethod
    def load(
        cls,
        env_file: Path | None = None,
    ) -> "Settings":
        if env_file is not None:
            load_dotenv(
                dotenv_path=env_file,
                override=False,
            )
        else:
            load_dotenv(override=False)

        execution_mode_raw = os.getenv(
            "EXECUTION_MODE",
            "simulated",
        ).strip().lower()

        if execution_mode_raw not in {
            "simulated",
            "llm",
        }:
            raise ValueError(
                "EXECUTION_MODE must be either "
                "'simulated' or 'llm'"
            )

        llm_provider_raw = os.getenv(
            "LLM_PROVIDER",
            "anthropic",
        ).strip().lower()

        if llm_provider_raw != "anthropic":
            raise ValueError(
                "LLM_PROVIDER currently supports only "
                "'anthropic'"
            )

        anthropic_api_key = os.getenv(
            "ANTHROPIC_API_KEY"
        )

        anthropic_model = os.getenv(
            "ANTHROPIC_MODEL",
            os.getenv(
                "CLAUDE_MODEL",
                "claude-sonnet-5",
            ),
        ).strip()

        if not anthropic_model:
            raise ValueError(
                "ANTHROPIC_MODEL must not be empty"
            )

        # Deliberately not validated as required here, even when
        # execution_mode is "llm" (5E-5D-6D) - Settings.load() runs for
        # every CLI invocation, including read-only commands (list,
        # inspect, show-tool-approval, approve/reject/modify/cancel-
        # tool-call) that never touch a provider at all. Requiring a
        # key at load time would make those commands demand
        # credentials they never use. create_llm_provider()
        # (src/executor_factory.py) still requires a non-empty key -
        # that check now runs at the one place a provider is actually
        # about to be constructed, not here.

        return cls(
            execution_mode=execution_mode_raw,
            llm_provider=llm_provider_raw,
            anthropic_api_key=anthropic_api_key,
            anthropic_model=anthropic_model,
            llm_timeout_seconds=_read_positive_float(
                "LLM_TIMEOUT_SECONDS",
                60.0,
            ),
            llm_max_retries=_read_non_negative_int(
                "LLM_MAX_RETRIES",
                2,
            ),
            llm_max_tokens=_read_positive_int(
                "LLM_MAX_TOKENS",
                4096,
            ),
            llm_max_tool_rounds=_read_positive_int(
                "LLM_MAX_TOOL_ROUNDS",
                8,
            ),
            llm_max_total_tokens=_read_positive_int(
                "LLM_MAX_TOTAL_TOKENS",
                100_000,
            ),
            debug_log_full_output=_read_bool(
                "DEBUG_LOG_FULL_OUTPUT",
                False,
            ),
            test_policy_path=os.getenv(
                "TEST_POLICY_PATH",
                "src/config/test_policy.json",
            ).strip(),
            approval_policy_path=os.getenv(
                "APPROVAL_POLICY_PATH",
                "src/config/approval_policy.json",
            ).strip(),
        )

    @property
    def uses_llm(self) -> bool:
        return self.execution_mode == "llm"

