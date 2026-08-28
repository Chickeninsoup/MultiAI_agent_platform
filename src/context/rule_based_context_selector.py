from __future__ import annotations

import re
from pathlib import Path

from src.context.context_file import ContextFile
from src.context.context_snapshot import ContextSnapshot
from src.context.path_exclusions import is_excluded

FALLBACK_FILES = (
    "src/main.py",
    "README.md",
)

_WORD_PATTERN = re.compile(r"[a-zA-Z0-9]+")
_MIN_WORD_LENGTH = 3


class RuleBasedContextSelector:
    """Default ContextSelector: keyword-overlap matching, no LLM/embeddings.

    Replaces the task-irrelevant hardcoded DEFAULT_CONTEXT_FILES with
    something explainable and deterministic - not a blind default
    swapped for an opaque smarter one. A repository file matches if a
    word in its filename stem overlaps, via substring in either
    direction, with a word extracted from the task description (e.g.
    "auth" from auth.py matches "authentication" in the task text,
    since one contains the other). Falls back to FALLBACK_FILES when
    nothing matches, so a request with no keyword overlap still gives
    the agent *something* rather than an empty context - deliberately
    not the same 5 files RunContextBuilder used to hardcode.

    A future embedding/vector-search selector replaces this class
    entirely rather than this growing smarter matching rules.
    """

    def select(
        self, task_description: str, repository_root: Path
    ) -> ContextSnapshot:
        keywords = self._extract_keywords(task_description)

        matches = [
            ContextFile(
                path=relative_path.as_posix(),
                reason=f"keyword match: {matched_word}",
            )
            for relative_path, matched_word in self._matching_files(
                repository_root, keywords
            )
        ]

        if matches:
            return ContextSnapshot(files=matches)

        return ContextSnapshot(
            files=[
                ContextFile(
                    path=path,
                    reason=(
                        "fallback: no keyword match in task "
                        "description"
                    ),
                )
                for path in FALLBACK_FILES
            ]
        )

    def _extract_keywords(self, task_description: str) -> set[str]:
        return {
            word.lower()
            for word in _WORD_PATTERN.findall(task_description)
            if len(word) >= _MIN_WORD_LENGTH
        }

    def _matching_files(
        self, repository_root: Path, keywords: set[str]
    ):
        for path in sorted(repository_root.rglob("*")):
            if not path.is_file():
                continue

            relative_path = path.relative_to(repository_root)

            if is_excluded(relative_path):
                continue

            matched_word = self._match_stem(path.stem, keywords)

            if matched_word is not None:
                yield relative_path, matched_word

    def _match_stem(
        self, stem: str, keywords: set[str]
    ) -> str | None:
        for raw_word in _WORD_PATTERN.findall(stem):
            word = raw_word.lower()

            if len(word) < _MIN_WORD_LENGTH:
                continue

            for keyword in keywords:
                if word in keyword or keyword in word:
                    return word

        return None
