from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from src.review.change_snapshot import ChangeSnapshot


class ChangeSnapshotBuilder:
    def build(
        self,
        *,
        run_id: str,
        run_directory: Path,
        repository_root: Path,
    ) -> ChangeSnapshot:
        del repository_root

        events = self._read_events(run_directory)

        changed_files = self._collect_changed_files(events)
        mutation_count = sum(
            1 for event in events if event.get("type") == "file_mutation"
        )
        test_results = self._collect_test_results(events)
        diff_path = self._resolve_diff_path(run_directory)

        return ChangeSnapshot(
            run_id=run_id,
            changed_files=changed_files,
            mutation_count=mutation_count,
            test_results=test_results,
            diff_path=diff_path,
        )

    @staticmethod
    def _read_events(
        run_directory: Path,
    ) -> list[dict[str, Any]]:
        events_path = run_directory / "events.jsonl"

        if not events_path.exists():
            return []

        events: list[dict[str, Any]] = []

        for line in events_path.read_text(
            encoding="utf-8"
        ).splitlines():
            if not line.strip():
                continue

            events.append(json.loads(line))

        return events

    @staticmethod
    def _collect_changed_files(
        events: list[dict[str, Any]],
    ) -> list[str]:
        changed_files: list[str] = []

        for event in events:
            if event.get("type") != "file_mutation":
                continue

            path = event.get("path")

            if path is not None and path not in changed_files:
                changed_files.append(path)

        return changed_files

    @staticmethod
    def _collect_test_results(
        events: list[dict[str, Any]],
    ) -> dict[str, Any]:
        test_results: dict[str, Any] = {}

        for event in events:
            if event.get("type") != "tool_result":
                continue

            if event.get("name") != "run_test":
                continue

            test_results["run_test"] = {
                "exit_code": event.get("exit_code"),
                "timed_out": event.get("timed_out"),
            }

        return test_results

    @staticmethod
    def _resolve_diff_path(
        run_directory: Path,
    ) -> str | None:
        diff_path = run_directory / "diff.patch"

        if not diff_path.exists():
            return None

        return str(diff_path)
