---
name: run-test-tool-5c3
description: "Stage 5C-3 (A-F) COMPLETE: run_test tool (name-only, whitelisted subprocess commands) -> TestPolicy/TestRunner -> policy-gated to agent-coder -> verified live as a full read_file->patch_file->run_test autonomous fix loop. Superseded/continued by [[human-review-gate-5c4]]."
metadata:
  node_type: memory
  type: project
  originSessionId: f3032f95-4fae-4ce6-8128-c86c03e5234d
---

Continuation of [[patch-file-tool-5c2]]. Same staged-commit workflow. All of 5C-3A–F done 2026-07-24, single commit `401cdb2` ("feat: add policy-controlled run_test tool"), pushed to `origin/main`.

## What was built

- **`src/services/tools/handlers/run_test_tool.py`** — `RunTestTool`. Input schema is *only* `test_name` (string) — no `command` field exists anywhere in the schema, so there is no way for Claude to pass an arbitrary shell command even in principle. `execute()` wires `TestPolicy.get_test(name)` → `TestRunner.run()` → `ToolResult`.
- **`src/services/tools/test_policy.py`** — `TestPolicy`/`TestDefinition`, loaded from `src/config/test_policy.json` (path configurable via new `Settings.test_policy_path` / env `TEST_POLICY_PATH`, default `"src/config/test_policy.json"`, resolved as `project_root / test_policy_path` in `LLMAgentRunExecutor.execute()`). Deliberately a **separate file from `tool-policy.json`**: `tool-policy.json` answers "can this agent use run_test at all", `test_policy.json` answers "what can run_test actually execute" — same separation-of-concerns the user was explicit about. `UnknownTestError` (`error_code=UNKNOWN_TEST`) propagates uncaught out of `RunTestTool.execute()`, picked up generically by `ToolExecutor`'s exception handler — same pattern as every other tool's errors.
- **`src/services/tools/test_runner.py`** — `TestRunner.run()`: `subprocess.run(command_list, shell=False, cwd=repository_root, timeout=..., capture_output=True, text=True)`. `shell=False` + argv-list (never a string) is the actual injection defense — `test_name` never touches a shell. Timeout caught as `TestRunResult(timed_out=True, exit_code=-1, ...)`, not a hang or an exception. stdout/stderr independently truncated to `max_output_chars`.
- **Critical design point, confirmed correct by user**: a failing test (non-zero exit code) is `ToolResult.success = True` — the tool executed correctly, it just reports the test didn't pass. `metadata = {test_name, exit_code, timed_out}`. This is what lets Claude keep iterating (see a failure, patch, re-run) instead of the run erroring out. Only `UnknownTestError` / a genuine execution problem is a tool failure.
- **Real bug found and fixed**: `test_policy.json`'s registered commands originally used bare `"python"`, which resolves via `PATH` to a pyenv shim lacking the `anthropic` package — so `run_test("unit")` would spuriously fail on `tests/llm/test_anthropic_provider_tools.py`'s collection, independent of any real bug in the code being tested. Fixed by changing both commands to `.venv/bin/python` (a relative path — confirmed empirically that `subprocess` resolves a slash-containing relative executable against the child's `cwd`, i.e. against `repository_root`, which is `project_root` in production and does have `.venv/`). **If this project's Python environment setup changes (e.g. Docker, no more bare `.venv/`), `test_policy.json` will need updating again** — this is inherently machine/environment-coupled, unlike the rest of the write-tool stack.
- **Policy wiring**: same pattern as `write_file`/`patch_file` — `RunTestTool` registered unconditionally in `executor_factory.create_tool_executor()` (which now requires an explicit `test_policy_path: Path` param, no default — every call site had to be updated, including two test files that construct `ToolExecutor`/`LLMAgentRunExecutor` directly with fake `tmp_path` repos, which now also need a synthetic `test_policy.json` written into their fake root or a real ones's path passed). `agents/agent-coder/tool-policy.json` → `run_test: {enabled: true}`; `agents/agent-general/tool-policy.json` → `run_test: {enabled: false}`.
- **No `file_mutation` event for `run_test`** — and no code change was needed to exclude it: the event is still gated purely on `"after_sha256" in result.metadata`, and `run_test`'s metadata never has that key (it doesn't touch files), so the existing generic mechanism naturally excludes it.

## Real end-to-end Claude verification (autonomous fix-verify loop, not simulated)

Built `tasks/task-run-test-loop/` (task + run-001) plus `sandbox/calculator.py` (deliberately buggy: `def add(a, b): return a - b`) and `sandbox/test_calculator.py` (asserts `add(2,3)==5`, fails pre-fix) — all committed as verification evidence, same precedent as `task-patch-test`/`task-20260713-001`. Task input **did not reveal the fix** (no "change - to +"), only described symptoms and required using `patch_file` (not `write_file`) then `run_test` to verify, continuing until it passes.

Real observed sequence in `events.jsonl`: `read_file(calculator.py)` → `read_file(test_calculator.py)` → `patch_file(old_text/new_text = full two-line function body, not just "a - b")` → `file_mutation{operation:"patch"}` → `run_test(test_name="unit")` → `tool_result{success:true}` (which ran the *entire* 244-test suite including this new one — `test_policy.json` only has whole-suite `unit`/`compile`, no single-file granularity) → `end_turn`. Zero `write_file` calls. Claude's final report accurately cited the real `245 passed` pytest output and correctly noted pre-existing `PytestCollectionWarning`s as unrelated noise rather than treating them as failures.

**Known gap in this verification**: the fix was correct on the first `patch_file` attempt, so this run demonstrated the "verify before declaring done" discipline but did **not** exercise the actual retry path (wrong patch → `run_test` fails → patch again). No test case for that exists yet — would need a task where a first attempt is plausibly wrong, which is hard to engineer without being contrived.

## Status: 5C-3 (and thus the whole write/patch/test tool arc, 5C-1 through 5C-3) is complete

## Status: superseded

5C-4 (the human review gate this stage anticipated as "git change management") turned out to be a human-approval checkpoint (`awaiting_review`/`approved`/`rejected` states + a `review` CLI command), not an Agent-facing `git_commit` tool — see [[human-review-gate-5c4]] for what was actually built. Auto-commit itself is still not implemented; kept here only as history for the `run_test`/`TestPolicy`/`TestRunner` design decisions.
