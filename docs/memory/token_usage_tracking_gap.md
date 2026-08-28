---
name: token-usage-tracking-gap
description: "RESOLVED (2026-07-22, stage 5B-5A): LLMRunExecutor now returns a cumulative LLMRunResult instead of a bare last-round LLMResponse"
metadata: 
  node_type: memory
  type: project
  originSessionId: 84526302-59c2-4874-af7e-0eda41019e28
---

`LLMRunExecutor.execute()` (src/llm_executor.py) used to run a multi-round tool-calling loop but return a single `LLMResponse`, so `_build_output()`/`_build_summary()` in `LLMAgentRunExecutor` reported only the last round's token usage as if it were the run's total.

**Status: fixed.** As of stage 5B-5A, `LLMRunExecutor.execute()` returns:

```python
@dataclass(frozen=True)
class LLMRunResult:
    final_response: LLMResponse
    total_input_tokens: int
    total_output_tokens: int
    llm_rounds: int
    tool_rounds: int
    tool_calls: int
```

`LLMAgentRunExecutor._build_output`/`_build_summary` now take `run_result: LLMRunResult` and read `run_result.final_response.text` plus the cumulative fields — `summary.md` additionally reports `Total tokens`/`LLM rounds`/`Tool rounds`/`Tool calls`. Covered by `tests/test_llm_executor_tools.py` and `tests/test_llm_agent_run_executor.py`. README's known-limitations section was updated to match; this memory is kept only as history — no further action needed here. Next related work is stage 5B-5B/5C (structured per-round `events.jsonl` audit log + tool error taxonomy), see [[agent-task-run-refactor]].
