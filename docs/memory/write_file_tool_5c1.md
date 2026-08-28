---
name: write-file-tool-5c1
description: "Stage 5C-1 (A-D) COMPLETE: write_file tool protocol -> safe filesystem kernel -> policy-gated activation (agent-coder only) -> sha256 file_mutation audit events. Superseded/continued by [[patch-file-tool-5c2]]."
metadata:
  node_type: memory
  type: project
  originSessionId: f3032f95-4fae-4ce6-8128-c86c03e5234d
---

The user is working through a numbered staged plan (5C-1A through 5C-1D, each its own commit) to add a write-capable tool to this agent platform, on branch `main` (pushed to `origin/main` after each stable point). All 4 sub-stages are done as of 2026-07-23, committed as `7262ca5` (5C-1A/B/C: "feat: add policy-controlled write_file tool") and `b5b0d28` (5C-1D: "feat: introduce audited write capability").

## What was built

- **`src/services/tools/handlers/write_file_tool.py`** — `WriteFileTool`. Strict input schema (`path`, `content`, `mode: create|overwrite`, default `create`, `additionalProperties: false`). `create` fails if the file exists; `overwrite` fails if it doesn't — no blended "upsert" mode. No auto-mkdir of parent directories (deliberate — the user rejected implicit directory creation as an audit/blast-radius risk; a future `create_directory` tool would be separate). Sensitive-path blocklist (`.git`, `.venv`, `venv`, `__pycache__` dirs; `.env`/`.env.*`/`id_rsa`/`id_ed25519` names; `.pem`/`.key` suffixes). Byte-size limit via `max_write_bytes` (checked against UTF-8 encoded length). Atomic write: `tempfile.mkstemp` in the target's own dir + `fsync` + `os.replace`, temp file cleaned up on any exception.
- **`src/services/tools/path_guard.py`** — new `resolve_repository_write_path()` alongside the existing read-only `resolve_repository_path()`. Requires the parent directory to already exist (raises `PathNotFoundError` otherwise), resolves symlinks in the parent chain to block escapes, and separately re-checks an existing target's real path in case the destination itself is a symlink pointing outside the repo.
- **`src/services/tools/tool_policy.py`** — `ToolPolicyEntry` gained `max_write_bytes: int | None`, validated the same way as `max_output_chars`; `ToolPolicy.get_max_write_bytes(tool_name, fallback)` added.
- **`src/executor_factory.py`** — `create_tool_executor()` now always registers `WriteFileTool` in the handlers list (reading `max_write_bytes` from that agent's policy). Registering it unconditionally is safe/intentional: exposure is still fully gated per-agent by `tool-policy.json` (`ToolExecutor.get_definitions()`/`_execute()` both check `tool_policy.is_enabled(name)`). This is the chosen pattern for future tools too — register once, gate via policy, not `if enabled: handlers.append(...)`.
- **New agent `agents/agent-coder/`** (`agent.json` role `coder`, `system-prompt.md`, `tool-policy.json`) — the only agent with `write_file: {enabled: true, max_write_bytes: 100000}`. `agents/agent-general/tool-policy.json` explicitly keeps `write_file: {enabled: false}`. No central agent registry exists — `AgentRepository.get_agent_dir(agent_id)` just does `agents_dir / agent_id`, so adding a new agent is purely a new directory, nothing else to wire up.
- **Audit trail**: `WriteFileTool` returns `before_sha256`/`after_sha256`/`bytes_written` in `ToolResult.metadata` (`before_sha256` is `None` for `create`). `LLMRunExecutor` (`src/llm_executor.py`) emits a `file_mutation` event to `events.jsonl` whenever `result.metadata` contains the key `after_sha256` — **deliberately keyed off metadata shape, not `tool_name == "write_file"`**, so a future `apply_patch`/`edit_file` tool gets audit events for free just by populating the same metadata keys, no `llm_executor.py` change needed.
- README updated: tool table now lists `write_file` (agent-coder only), a new "File mutation 审计" subsection documents the `file_mutation` event, and the stale "tools are all read-only" known-limitation bullet was corrected to describe the actual current gap (no append/diff editing yet).

## Why

The user is deliberately sequencing this as protocol → safety kernel → policy → audit, each stage validated and committed before the next, specifically to avoid mixing concerns later. Explicit user reasoning for committing at 5C-1D rather than batching further: the `file_mutation`-via-metadata-shape design is an interface worth freezing early, since `apply_patch` will reuse it — deferring the commit risks conflating write_file audit changes with new-tool changes in the same diff, raising debugging cost.

## Status: superseded

5C-2 (`patch_file`, the diff/patch-based edit tool this stage anticipated) is done — see [[patch-file-tool-5c2]] for what was built, the shared `file_writer.py` extraction, and the real end-to-end Claude verification. Kept here only as history for the write_file-specific design decisions (no auto-mkdir, strict create/overwrite split, sensitive-path list).
