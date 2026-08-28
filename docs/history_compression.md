# Short-term History Compression v1

## Overview

This document summarizes the design and implementation of the first version of the Agent short-term history compression system.

The goal is to prevent long-running agent sessions from exceeding LLM context and cumulative token limits while preserving:

- tool protocol correctness
- important state-changing actions
- deterministic behavior
- debuggability

The system focuses on dynamic conversation history compression.

**It does not solve static project context overhead** (for example, large repository snapshots injected into the initial prompt).

## Problem

During multi-round agent execution, every LLM request contains:

```
system prompt
+
tools
+
initial task context
+
conversation history
```

The conversation history grows after every:

- assistant response
- tool call
- tool result

Without compression:

```
Round 1:
task + context

Round 20:
task + context + all previous interactions

Round 100:
task + context + huge history
```

This creates cumulative token growth.

## Design Goals

The compression system must:

**Preserve complete tool exchanges**

```
assistant:
    tool_use

user:
    tool_result
```

must be treated as an atomic unit.

**Never modify durable history**

The original message list remains unchanged. Compression only creates a temporary view for the next LLM request.

**Support token-based budgets**

Message count is not a reliable proxy for context size.

**Separate decision from execution**

The system should decide *what to keep* before actually applying *which messages are sent*.

**Provide explainability**

Every compression decision should be inspectable.

## Architecture

### Pipeline

```
LLMMessage[]
      |
      v
MessageGroupBuilder
      |
      v
MessageGroup[]
      |
      v
GroupSelector
      |
      v
CompactionPlan
      |
      v
apply_compaction_plan()
      |
      v
LLMRequest.messages
      |
      v
Provider
```

### Core Components

#### 1. MessageGroup

Location: `src/context/history/message_group.py`

Purpose: convert flat messages into logical history units.

Supported group types: `INITIAL_TASK`, `NORMAL`, `TOOL_EXCHANGE`.

Example:

```
Message 0:
initial user task
        ↓
INITIAL_TASK

Tool exchange:

Message 1:
assistant tool_use

Message 2:
user tool_result
        ↓
TOOL_EXCHANGE
```

A tool exchange is always selected or removed together.

#### 2. MessageGroupBuilder

Location: `src/context/history/message_group_builder.py`

Responsibilities:

- identify tool exchanges
- preserve message indices
- attach tool metadata

Example:

```python
MessageGroup(
    indices=(5, 6),
    kind=TOOL_EXCHANGE,
    tool_name="apply_patch",
)
```

Important: the builder does not modify messages. It only creates a structural view.

#### 3. HistorySizeEstimator

Location: `src/context/history/history_size_estimator.py`

Purpose: provide a token estimation abstraction.

Current implementation: `CharBasedHistorySizeEstimator`, uses `characters // 4` as an approximate fallback.

**Important discovery**: real Anthropic token usage is approximately **1.7x - 2x** larger than this estimate for code-heavy contexts.

The estimator is intentionally isolated so a provider tokenizer can replace it later.

#### 4. HistoryBudget

Location: `src/context/history/history_budget.py`

Defines:

```python
HistoryBudget(max_tokens=...)
```

This budget only controls conversation history. It is different from:

- total LLM context limit
- cumulative run token limit
- static project context budget

#### 5. ToolRetentionPolicy

Location: `src/context/history/tool_retention_policy.py`

Purpose: classify tool exchanges.

Current categories: `PROTECTED`, `NORMAL`, `EVICTABLE`.

- Protected: `apply_patch`, `write_file`, `create_file`, `delete_file`, `git_commit`
- Evictable: `read_file`, `list_files`, `search`
- Unknown tools: `NORMAL`

Safety principle: unknown actions are preserved by default.

#### 6. GroupSelector

Location: `src/context/history/group_selector.py`

Purpose: choose which groups survive under a token budget.

Selection priority:

```
INITIAL_TASK
        ↓
PROTECTED TOOL EXCHANGES
        ↓
RECENT NORMAL CONTEXT
        ↓
OLDER EVICTABLE GROUPS
```

**Important behavior change**: the previous algorithm kept a *continuous recent suffix*. The current algorithm does *priority-based selection*, so the retained groups are not necessarily continuous.

However, tool protocol safety remains guaranteed because selection happens at group level.

#### 7. CompactionPlan

Location: `src/context/history/compaction_plan.py`

Purpose: represent a decision.

```python
CompactionPlan(
    original_count=100,
    retained_indices=[0, 80, 81, 82],
)
```

It does not modify data.

#### 8. CompactionReport

Purpose: explain decisions.

```json
{
  "removed_groups": [
    {"tool": "read_file", "reason": "budget_limit"}
  ],
  "retained_groups": [
    {"tool": "apply_patch", "reason": "protected"}
  ]
}
```

Used for: `events.jsonl`, debugging, future optimization.

## Runtime Integration

Integration point: `LLMRunExecutor`.

Before every `provider.complete()`:

```
full durable history
        |
        v
HistoryCompactor
        |
        v
CompactionPlan
        |
        v
temporary request messages
        |
        v
Claude API
```

Important: the original `messages` continues growing. Only `current_request.messages` is compressed.

## Testing Results

Final validation: **534 tests passed**. No compile errors.

### Stress Test

Scenario: initial task + 20 tool exchanges.

Verified:

- compression triggered
- 50% compression
- zero broken tool pairs
- deterministic output
- original history unchanged

### Benchmark

80-round synthetic agent history.

| | input tokens |
|---|---|
| Without compression | 1,346,682 |
| With compression | 547,226 |

Compression: **59.36%**. Tool protocol violations: **0**.

## Smoke Test Findings

Real executor smoke tests successfully verified:

```
LLMRunExecutor
        |
        v
CompactionReport
        |
        v
events.jsonl
```

However, history compression was **not** the main bottleneck. Observed: `initial_message` (static project context) already consumed tens of thousands of tokens.

**Conclusion**: history compression solves dynamic history growth, but does not solve large static context injection.

## Current Limitations

### 1. Static Context Too Large

Current issue: `initial task + project snapshot` may dominate token usage.

Future work: ContextSelector optimization, chunk-level retrieval, lazy file loading, repository memory.

### 2. No Semantic Dependency Tracking

Current selector knows tool importance, but not "this patch depends on this previous read_file."

Future: dependency-aware retention.

### 3. Token Estimation

Current: character-based estimation.

Future: provider tokenizer integration.

## Final Status

Short-term History Compression v1:

| Area | Status |
|---|---|
| Architecture | COMPLETE |
| Runtime integration | COMPLETE |
| Safety guarantees | COMPLETE |
| Explainability | COMPLETE |
| Benchmark | COMPLETE |

Next major milestone: **Static Context Optimization**.

Goal: reduce `initial_message` token cost before implementing more advanced memory systems.
