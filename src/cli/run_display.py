from __future__ import annotations

from src.domain.events.run_event import RunEvent
from src.models import RunDefinition
from src.run_query_service import RunInspection


def format_run_list(runs: list[RunDefinition]) -> str:
    if not runs:
        return "No runs found."

    lines: list[str] = ["Recent Runs"]

    for run in runs:
        changed_files = run.metadata.get("changed_files", [])

        lines.append("")
        lines.append(run.id)
        lines.append("Task:")
        lines.append(run.task_id)
        lines.append("Agent:")
        lines.append(run.agent_id)
        lines.append("Status:")
        lines.append(run.status)
        lines.append("Changes:")
        lines.append(
            f"{len(changed_files)} file"
            f"{'' if len(changed_files) == 1 else 's'}"
        )

    return "\n".join(lines)


def format_run_inspection(inspection: RunInspection) -> str:
    run = inspection.run
    lines: list[str] = []

    lines.append(f"Run: {run.id}")
    lines.append(f"Task: {inspection.task_id}")
    lines.append(f"Agent: {run.agent_id}")
    lines.append("")
    lines.append("Status:")
    lines.append(run.status)
    lines.append("")

    lines.append("Timeline:")
    if inspection.timeline.events:
        for index, event in enumerate(inspection.timeline.events, start=1):
            lines.append(f"{index}. {_format_event_line(event)}")
    else:
        lines.append("(no events recorded for this run)")
    lines.append("")

    lines.append("Changes:")
    if inspection.snapshot and inspection.snapshot.changed_files:
        for path in inspection.snapshot.changed_files:
            lines.append(f"- {path}")
    else:
        lines.append("(none)")
    lines.append("")

    lines.append("Tests:")
    if inspection.snapshot and inspection.snapshot.test_results:
        for test_name, test_result in inspection.snapshot.test_results.items():
            lines.append(f"{test_name}:")
            for key, value in test_result.items():
                lines.append(f"  {key}: {value}")
    else:
        lines.append("(none)")

    return "\n".join(lines)


def _format_event_line(event: RunEvent) -> str:
    name = event.data.get("name")

    if event.event_type == "tool_call" and name:
        return f"tool_call {name}"

    if event.event_type == "tool_result" and name:
        return f"tool_result {name}"

    if event.event_type == "file_mutation":
        operation = event.data.get("operation", "")
        return f"file_mutation {operation}".rstrip()

    return event.event_type
