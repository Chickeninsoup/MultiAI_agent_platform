from src.execution import (
    RunExecutionContext,
    RunExecutionResult,
)


class SimulatedRunExecutor:
    """Produce deterministic output without calling an external model."""

    def execute(
        self,
        context: RunExecutionContext,
    ) -> RunExecutionResult:
        output = self._build_output(context)
        summary = self._build_summary(context)

        return RunExecutionResult(
            output=output,
            summary=summary,
        )

    @staticmethod
    def _build_output(
        context: RunExecutionContext,
    ) -> str:
        return (
            "# Run Output\n\n"
            f"Run `{context.run.id}` completed successfully.\n\n"
            f"Agent: `{context.agent.id}`\n\n"
            "## Input Received\n\n"
            f"{context.run_input}\n"
        )

    @staticmethod
    def _build_summary(
        context: RunExecutionContext,
    ) -> str:
        return (
            "# Run Summary\n\n"
            f"- Run ID: `{context.run.id}`\n"
            f"- Agent ID: `{context.agent.id}`\n"
            "- Status: `completed`\n"
            "- Summary: The simulated execution workflow "
            "completed successfully.\n"
            "- Important findings: Task, Run, and Agent "
            "metadata were loaded successfully.\n"
            "- Decisions made: Keep execution behavior "
            "behind a replaceable executor interface.\n"
            "- Remaining work: Add an LLM-backed executor.\n"
        )
