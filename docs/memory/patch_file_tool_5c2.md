---
name: patch-file-tool-5c2
description: "Stage 5C-2 (A-E) COMPLETE: patch_file tool (exact unique-match text replace) -> shared file_writer.py kernel -> policy-gated to agent-coder -> file_mutation audit -> verified end-to-end against real Anthropic API. Superseded/continued by [[run-test-tool-5c3]]."
metadata:
  node_type: memory
  type: project
  originSessionId: f3032f95-4fae-4ce6-8128-c86c03e5234d
---

Continuation of [[write-file-tool-5c1]]. Same staged-commit workflow (implement sub-stage → full test suite + `compileall` → ask before commit/push, never assume). All of 5C-2A–E done 2026-07-23, single commit `bc0665f` ("feat: add policy-controlled patch_file tool"), pushed to `origin/main` after explicit confirmation.

## What was built

- **`src/services/tools/handlers/patch_file_tool.py`** — `PatchFileTool`. Input: `path`, `old_text` (must be non-empty), `new_text` (may be empty string — deletion). `find_patch_location(content, old_text)` uses `content.count(old_text)`: 0 matches → `PatchMatchNotFoundError`, >1 matches → `PatchAmbiguousMatchError` (no partial/fuzzy matching, no line numbers — exact substring only). Error codes: `PATCH_FILE_NOT_FOUND`, `PATCH_MATCH_NOT_FOUND`, `PATCH_AMBIGUOUS_MATCH`.
- **Two entry points, deliberately kept separate**: `preview_patch()` (read-only, returns `updated_content` for tests) and `apply_patch()` (the real mutating path — does NOT call `preview_patch()` internally). The user was explicit about why: preview-then-apply as two calls is a TOCTOU bug (file can change between the read and the write); `apply_patch()` does read→verify→splice→write as one atomic sequence instead.
- **`src/services/tools/file_writer.py`** (new, extracted from `write_file_tool.py`) — `calculate_sha256(content: str) -> str` and `atomic_write_text(*, target_path, content)` (mkstemp + fsync + os.replace). Both `write_file` and `patch_file` now share this instead of each having their own copy — the user's explicit rationale: duplicated atomic-write logic in two tools "will definitely drift" over time. `write_file_tool.py` was refactored to use it too (its own `_atomic_write_text` was deleted). Side effect worth knowing: `calculate_sha256` takes a `str`, so `write_file`'s `before_sha256` now comes from `target_path.read_text(encoding="utf-8")` instead of raw `read_bytes()` — a real (if narrow) behavior change: overwriting a pre-existing file with invalid-UTF-8 bytes now raises `UnicodeDecodeError` while hashing, instead of silently hashing raw bytes. Flagged to the user, not blocking, no test covers it.
- **Policy/wiring**: `agents/agent-coder/tool-policy.json` gets `patch_file: {enabled: true}`; `agents/agent-general/tool-policy.json` gets `patch_file: {enabled: false}` (explicit, for parity with `write_file`'s explicit disable). `executor_factory.py` registers `PatchFileTool()` unconditionally in the handlers list, same pattern as `write_file` (register once, gate via policy — this is now the established pattern for every new tool).
- **Audit bug found and fixed**: `patch_file`'s metadata key for the verb is `operation` (`"patch"`), while `write_file`'s is `mode` (`"create"`/`"overwrite"`). The generic `file_mutation` event builder in `llm_executor.py` only read `metadata.get("mode")`, so wiring up `patch_file` unchanged would have silently emitted `operation: null`. Caught by a new test (`test_patch_file_result_emits_file_mutation_event` in `tests/test_llm_executor_tools.py`), not by inspection. Fixed with `metadata.get("operation", metadata.get("mode"))` — still no tool-name hardcoding, just two accepted synonym keys. **If adding another mutation tool, populate `metadata["operation"]`** (the newer/preferred key) rather than reviving `mode`.
- **README** (`README.md`) updated: tool table now lists `patch_file`, the "File mutation 审计" section documents both `operation` values and the mode/operation bug+fix, known-limitations section corrected (patch_file covers single precise edits, no multi-hunk unified-diff support; no restricted test/command runner yet).

## Real end-to-end Claude verification (not simulated)

Built a dedicated `tasks/task-patch-test/` (task + run-001, `agent_id: agent-coder`) plus `sandbox/hello.py` as a scratch target — all committed to the repo as verification evidence (user explicitly chose "keep & commit" over deleting, matching the precedent set by `task-20260713-001`'s earlier verification runs). Task instructed Claude to change `print("Hello")` → `print("Hello Agent")` using `patch_file` specifically, not `write_file`, requiring a distinct old/new text pair to avoid a trivial/ambiguous match.

Real tool sequence observed in `events.jsonl`: `read_file` → `patch_file` (with `old_text` = the full `"def greet():\n    print(\"Hello\")"` block, not just `"Hello"` — Claude chose a safely-unique match on its own, unprompted with that specific example) → `read_file` (self-verification) → `end_turn`. Zero `write_file` calls anywhere in the trace. `file_mutation` event fired correctly with `operation: "patch"` and correct before/after sha256. File on disk matched exactly.

Run this in the project's `.venv` (`/.venv/bin/python -m src.main run <task-id>`), not the bare system python — the system python lacks the `anthropic` package and fails immediately on `create_llm_provider`.

## Status: superseded

5C-3 (`run_test`, the restricted test/command runner this stage anticipated) is done — see [[run-test-tool-5c3]] for what was built and the real Claude fix-verify loop verification. Kept here only as history for the patch_file-specific design decisions (TOCTOU-avoiding single-pass apply, unique-match-only semantics).
