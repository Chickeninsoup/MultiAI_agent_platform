# Review module design notes

## `ChangeSnapshot.test_results` shape may need to evolve

Current shape (5C-4B), keyed by tool name, one entry per tool:

```json
{
  "run_test": {
    "exit_code": 0,
    "timed_out": false
  }
}
```

This only works because a Run currently calls `run_test` with at most one
meaningfully-tracked result. Once Runs can invoke multiple distinct test
commands (e.g. `pytest`, `compile`, `lint`) and we want to keep each
invocation's result instead of last-call-wins, this dict-keyed-by-tool-name
shape won't hold more than one result per tool.

Possible future shape — a list, one entry per test invocation:

```json
{
  "tests": [
    {"name": "pytest", "exit_code": 0},
    {"name": "compile", "exit_code": 0}
  ]
}
```

Not changing this now — 5C-4's current goal is the minimal end-to-end
review loop, not a fully general test-result schema. Revisit when a Run
actually needs to run more than one distinct test command and surface all
of their results (not just the last `run_test` call's).
