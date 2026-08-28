# Claude Agent Platform

一个用于管理「任务（Task）→ 运行（Run）→ 智能体（Agent）」工作流的私有 Python 平台。Agent 通过 Anthropic Claude API 执行任务，并且现在**可以真实调用工具**（读文件、列目录、查 git 状态/diff，特定 Agent 还能创建/修改文件、跑受限的测试命令）来完成任务，而不只是根据静态快照臆测答案。

> 早期原型阶段，个人项目，正在快速迭代。这份 README 反映的是代码库**当前**的真实状态，不是规划中的功能。

---

## 这是什么

平台围绕三个核心实体组织工作：

- **Task（任务）**：一个长期存在的工作项，比如"审查项目架构"。一个 Task 可以包含多个 Run，Run 之间共享同一份 `background.md`（任务背景，会随着每个 Run 完成后累积更新）。
- **Run（运行）**：Task 下的一次具体执行。每个 Run 有自己的输入（`input.md`）、输出（`output.md`）和摘要（`summary.md`），由某一个 Agent 执行。
- **Agent（智能体）**：一个可复用的执行角色配置——system prompt、默认模型、资源限制（token/内存/超时）、工具权限策略（`tool-policy.json`）。Agent 本身不绑定某个 Task，可以被多个 Task 复用。

一个 Task 可以有很多轮 Run，每一轮可以用不同的 Agent 执行，Run 完成后的结论会被追加进 Task 的共享背景，供后续 Run 参考——这是为将来多 Agent 协作、任务连续推进设计的结构。

## 两种执行模式

由 `.env` 里的 `EXECUTION_MODE` 控制：

| 模式 | 说明 |
|---|---|
| `simulated` | 不调用任何模型，`SimulatedRunExecutor` 生成确定性的占位输出。用于跑通流程、写测试，不消耗 API 额度。 |
| `llm` | 真正调用 Anthropic API（`claude-sonnet-5`），Agent 可以使用真实工具执行多轮任务。 |

## 工具调用能力（当前重点）

Agent 在 `llm` 模式下有 4 个只读工具，外加三个默认关闭、只对 `agent-coder` 开放的能力更强的工具：

| 工具 | 作用 |
|---|---|
| `list_files` | 列出仓库内某个目录下的文件/子目录 |
| `read_file` | 读取仓库内某个文本文件，支持指定行号范围 |
| `git_status` | 查看当前分支和工作区状态（`git status --short --branch`） |
| `git_diff` | 查看未暂存或已暂存的改动（`git diff`） |
| `write_file` | 在仓库内创建（`mode: create`）或整篇覆盖（`mode: overwrite`）一个 UTF-8 文本文件；只在 `agents/agent-coder/tool-policy.json` 里 `enabled: true`，`agent-general` 保持关闭 |
| `patch_file` | 把文件里某一段**精确且唯一**的 `old_text` 替换成 `new_text`（`new_text` 可以是空字符串，表示删除）；`old_text` 在文件里不存在或出现不止一次都会直接失败，不会猜测意图。同样只在 `agent-coder` 开放。 |
| `run_test` | 运行一个**预先在平台侧注册好**的测试命令（目前是 `unit`/`compile`），返回 exit code + stdout/stderr；Agent 只能传 `test_name`，传不了任意 shell 命令。同样只在 `agent-coder` 开放。 |

**关键设计点**：

- 所有工具都通过 `PathGuard`（`src/services/tools/path_guard.py`）做路径边界检查——请求路径必须解析到仓库根目录以内，拒绝 `../` 逃逸和软链接逃逸；`write_file`/`patch_file` 都额外用 `resolve_repository_write_path()` 处理目标文件尚不存在的情况（不自动创建父目录，父目录本身的软链接逃逸也会被拒绝）。
- `write_file` 不会自动覆盖：`create` 遇到已存在的文件直接报错，`overwrite` 遇到不存在的文件也直接报错，两种模式语义互不兼容；写入内容有按字节数的上限（`max_write_bytes`），`.git`/`.env`/私钥/虚拟环境等敏感路径永远拒绝；实际落盘用 `mkstemp` + `fsync` + `os.replace` 做原子替换，避免进程中途崩溃留下半个文件。
- `patch_file`（`src/services/tools/handlers/patch_file_tool.py`）设计成不做 preview-then-apply 两阶段（会有 TOCTOU 风险：预览之后、真正写入之前文件可能已被改动），而是一次 `apply_patch()` 调用里完成"读取→用 `content.count(old_text)` 校验唯一匹配→拼接新内容→写入"的全过程。`write_file` 和 `patch_file` 共享同一份写入内核（`src/services/tools/file_writer.py` 的 `calculate_sha256()`/`atomic_write_text()`），避免两个工具的原子写入逻辑各自实现、逐渐漂移。
- `run_test`（`src/services/tools/handlers/run_test_tool.py`）刻意**不是**一个通用 shell 工具——它只接受 `test_name`，不接受 `command`。实际能跑什么由平台侧的 `TestPolicy`（`src/services/tools/test_policy.py`，配置文件 `src/config/test_policy.json`，路径可通过 `.env` 的 `TEST_POLICY_PATH` 覆盖，与 `tool-policy.json` 分开维护——前者回答"这个 Agent 能不能用 `run_test`"，后者回答"`run_test` 能跑哪些命令"，权限和可执行内容两件事不揉在一起）把 `test_name` 映射到一个固定的 argv 列表（例如 `unit` → `[".venv/bin/python", "-m", "pytest", "-q"]`）。`TestRunner`（`src/services/tools/test_runner.py`）用 `subprocess.run(..., shell=False, cwd=repository_root, timeout=...)` 执行，`shell=False` 意味着 `test_name` 不可能被拼进一个 shell 字符串去注入任意命令；超时会被捕获为 `timed_out=True` 而不是让整个 Run 卡死；stdout/stderr 分别按 `max_output_chars` 截断。**测试失败不是工具失败**：`run_test` 只要成功执行了命令，无论 exit code 是 0 还是非 0，`ToolResult.success` 都是 `true`——失败信息通过 `metadata["exit_code"]`/`metadata["timed_out"]` 和 stdout/stderr 传给模型，让它自己判断要不要继续修。
- 每个 Agent 有自己独立的 `tool-policy.json`（`default: allow/deny` + 每个工具的 `enabled`/`max_output_chars`/`max_write_bytes`），决定它能用哪些工具、单次工具输出最多多少字符、单次写入最多多少字节。
- `ToolExecutor`（`src/services/tools/tool_executor.py`）是统一调度层：按名字找 handler、按策略校验是否启用、捕获异常统一转成失败态 `ToolResult`，不会让一次工具调用失败直接炸掉整个 Run。
- `LLMRunExecutor`（`src/llm_executor.py`）实现真正的**多轮工具调用循环**：请求模型 → 如果模型要调用工具就执行 → 把工具结果作为下一轮消息喂回去 → 再次请求，直到模型给出最终文本回答。有 `max_tool_rounds`（默认 8 轮）和 `max_total_tokens`（默认 100000）两道保险，防止死循环或失控的开销。
- `LLMAgentRunExecutor` 是适配层，把 Task/Run/Agent 那一套 `RunExecutionContext` 翻译成 `LLMRequest`，按当前 Run 的 Agent 现建对应的 `ToolExecutor`，再把最终结果翻译回 `RunExecutionResult`（Markdown 格式的 output/summary）。

这条链路已经用真实 API 端到端验证过（`tasks/task-20260713-001` 的 run-007）：模型依次真实调用了 `list_files`/`read_file`/`git_status`/`git_diff`，返回内容和仓库实际状态完全对得上。

`LLMRunExecutor.execute()` 返回的是 `LLMRunResult`（`final_response` + 整个 Run 累计的 `total_input_tokens`/`total_output_tokens`/`llm_rounds`/`tool_rounds`/`tool_calls`），不是裸的 `LLMResponse`——output.md/summary.md 里的 token 用量和轮次/工具调用次数都是整个 Run 的累计值，不是只看最后一轮。

### 每轮执行审计（`events.jsonl`，实时写入）

每次 Run 除了 `output.md`/`summary.md`，还会在同一个 Run 目录下实时写一个 `events.jsonl`——每产生一个事件就立即 `append` 一行并 flush（`src/run_events.py` 的 `JsonlRunEventSink`），不是等 Run 完全结束后再一次性落盘。这意味着即使 Run 中途崩溃、被杀掉，或者触发了轮次/token 限制，**之前已经发生的事件依然会留在文件里**，可以直接用 `tail -f` 实时观察：

```bash
tail -f tasks/<task-id>/runs/<run-id>/events.jsonl
```

事件类型：

```jsonl
{"type": "llm_response", "round": 1, "stop_reason": "tool_use", "input_tokens": 12552, "output_tokens": 226}
{"type": "tool_call", "round": 1, "tool_call_id": "toolu_...", "name": "list_files", "input": {"path": "src/services/tools/handlers/"}}
{"type": "tool_result", "round": 1, "tool_call_id": "toolu_...", "name": "list_files", "success": true, "error_code": null, "duration_ms": 1, "output_chars": 265, "truncated": false}
{"type": "llm_response", "round": 2, "stop_reason": "tool_use", "input_tokens": 12898, "output_tokens": 503}
{"type": "run_limit_exceeded", "limit": "max_tool_rounds", "configured_limit": 1, "actual_value": 2, "round": 2}
{"type": "run_failed", "error_type": "LLMRunLimitError", "message": "Maximum tool rounds exceeded."}
```

- `llm_response`：每次调用 Provider 后记一条，`round` 是第几次调用模型（不是"第几次工具调用"）。
- `tool_call`：模型**请求**了什么——`round`、`tool_call_id`、`name`、参数（`input`）。只记请求，不含执行结果。
- `tool_result`：平台**实际执行**的结果——成功/失败、`error_code`、`output_chars`、`truncated`、`duration_ms`（`ToolExecutor.execute()` 统一计时，成功/失败路径都有）、`exit_code`/`timed_out`（只有 `run_test` 会填，其它工具恒为 `null`——这两个字段是 5C-4 加的：`run_test` 的 `ToolResult.success` 恒为 `true`（测试失败不算工具失败），所以不把 `exit_code` 也带进事件的话，事件日志根本没法区分"测试通过"和"测试失败"）。`tool_call`/`tool_result` 是两条独立事件，不合并成一条。
- `run_limit_exceeded`：触发 `max_total_tokens`/`max_tool_rounds` 限制时记一条（`limit`/`configured_limit`/`actual_value`/`round`），紧接着会抛出 `LLMRunLimitError`。
- `run_completed`：Run 正常结束（`end_turn`，无更多工具调用）时记一条，带累计的 `llm_rounds`/`tool_rounds`/`tool_calls`/`total_input_tokens`/`total_output_tokens`。
- `run_failed`：`LLMRunExecutor.execute()` 内部只要抛出任何异常（包括 `run_limit_exceeded` 之后的 `LLMRunLimitError`），外层都会补记一条 `run_failed`（`error_type`/`message`），然后原样把异常继续往上抛——所以触发限制的 Run 会同时看到 `run_limit_exceeded` 和 `run_failed` 两条。
- **默认不记录工具的完整输出**（可能是完整文件内容或完整 git diff，体积大、可能包含源码/敏感信息、和 output.md 里的内容重复）。只有把 `.env` 里的 `DEBUG_LOG_FULL_OUTPUT` 设为 `true` 时，`tool_result` 事件才会额外带上完整的 `output` 字段；`tool_call` 的参数（`input`）本身体积通常很小，默认就会记。

`error_code` 目前的取值集合（`src/services/tools/tool_executor.py`/`path_guard.py`/`git_command.py`/`read_file_tool.py`）：`UNKNOWN_TOOL`、`TOOL_DISABLED`、`INVALID_TOOL_INPUT`、`PATH_OUTSIDE_REPOSITORY`、`PATH_NOT_FOUND`、`GIT_COMMAND_FAILED`、`TOOL_EXECUTION_FAILED`（兜底）——看到失败的 Run，可以直接从 `error_code` 判断问题出在模型选择、policy 拒绝、输入格式、路径安全、Git 环境还是工具实现本身。

### File mutation 审计

写入类工具（`write_file`/`patch_file`）成功执行后，`events.jsonl` 里除了通用的 `tool_result`，还会额外多记一条 `file_mutation`：

```jsonl
{"type": "file_mutation", "round": 1, "tool_call_id": "toolu_...", "operation": "create", "path": "src/example.py", "before_sha256": null, "after_sha256": "9f86d0...", "bytes_written": 13}
{"type": "file_mutation", "round": 2, "tool_call_id": "toolu_...", "operation": "patch", "path": "sandbox/hello.py", "before_sha256": "61f542f8...", "after_sha256": "726eb477...", "bytes_written": 38}
```

- `operation`：`write_file` 是 `create`/`overwrite`，`patch_file` 恒为 `patch`。
- `before_sha256`：写入前文件内容的 sha256；`write_file` 的 `create` 场景没有旧文件，恒为 `null`。
- `after_sha256`：写入后文件内容的 sha256。
- `bytes_written`：写入的 UTF-8 字节数（不是字符数）。

`LLMRunExecutor`（`src/llm_executor.py`）判断是否要发这条事件，看的是 `ToolResult.metadata` 里有没有 `after_sha256` 这个 key，不是硬编码判断 `tool_name == "write_file"`——接入 `patch_file` 时完全没有改这部分逻辑，只是让 `patch_file` 的 `metadata` 也带上同样几个字段。中间踩过一个坑：`write_file` 把操作类型放在 `metadata["mode"]` 里，`patch_file` 放在 `metadata["operation"]` 里，两个字段名不一致，导致 `file_mutation` 事件一开始把 `patch_file` 的 `operation` 记成了 `null`（被 `tests/test_llm_executor_tools.py::test_patch_file_result_emits_file_mutation_event` 抓到）——现在读取时是 `metadata.get("operation", metadata.get("mode"))`，两种字段名都认。`run_test` 不产出 `file_mutation`：它的 `metadata` 里没有 `after_sha256`（本来就不改文件），所以同一条判断逻辑自然把它排除在外，不需要额外的"排除列表"。

`LLMRunExecutor` 通过一个 `RunEventSink` 协议（`src/run_events.py`）解耦事件的产生和落盘：`NullRunEventSink`（默认，不注入时丢弃事件）、`InMemoryRunEventSink`（测试用）、`JsonlRunEventSink`（生产用，`LLMAgentRunExecutor` 注入，指向 `RunRepository.get_events_file()` 对应的路径，构造时 `truncate_existing=True` 清空同名旧文件，避免重跑同一个 `run_id` 时事件被追加污染）。`LLMRunResult.events` 仍然保留了同一份事件列表（内存副本），供不需要读文件的调用方直接使用。

### CLI 输出摘要

`RunService.execute()` 不再直接 `print`，而是返回一个结构化的 `RunServiceResult`（`task_id`/`run_id`/`agent_id`/`status`/`output_path`/`summary_path`/`events_path`，以及可选的 `llm_rounds`/`tool_rounds`/`tool_calls`/`total_input_tokens`/`total_output_tokens`——这些来自 `RunExecutionResult.metadata`，LLM 路径会填，simulated 路径没有则为 `None`）。`src/main.py` 基于这个结果打印：

```text
$ python -m src.main run task-20260713-001
Completed run: run-022
Output:  tasks/task-20260713-001/runs/run-022/output.md
Summary: tasks/task-20260713-001/runs/run-022/summary.md
Events:  tasks/task-20260713-001/runs/run-022/events.jsonl
Usage: 27673 input / 1195 output tokens, 2 LLM round(s), 1 tool round(s), 2 tool call(s)
```

如果 Run 执行失败（`LLMAgentRunExecutor.execute()` 抛出任何异常），`RunService.execute()` 会把异常分类、把 Run 标记为 `interrupted`（可重试）或 `failed`（不建议重试）、再包装成 `RunExecutionFailedError`（带 `run_id`/`agent_id`/**分类后的真实状态**/`category`/`retryable`/`events_path`/原始异常）抛出，`main.py` 据此打印：

```text
$ LLM_MAX_TOOL_ROUNDS=1 python -m src.main run task-20260713-001
Run failed: run-025
Status: interrupted
Category: LIMIT_EXCEEDED (retryable: True)
Error: Maximum tool rounds exceeded.

Events preserved:
  tasks/task-20260713-001/runs/run-025/events.jsonl

Retry with: python -m src.main resume run-025
```

`Status`/`Category`/`retryable` 都是真实持久化到 `run.json` 里的（`error_category`/`error_message`/`retryable` 三个字段），不是硬编码——`RunService` 从不会把失败的 Run 标记为 `completed`，具体标成 `interrupted` 还是 `failed` 取决于错误分类（见下面"Run 状态机与恢复"）。

## Run 状态机与恢复

一次 Run 的状态不再只有 `in_progress`/`completed` 两种：

```text
in_progress → completed                （正常结束，且不需要人工审核）
in_progress → awaiting_review          （正常结束，但改动了文件，等待人工审核）
awaiting_review → approved             （人工在 review 命令里批准）
awaiting_review → rejected             （人工在 review 命令里拒绝）
in_progress → interrupted              （可重试的失败：限流/Provider 抖动/进程崩溃）
in_progress → failed                   （不建议重试的失败：配置错误/内部 bug）
```

`status` 字段本身现在没有对应的 `Literal`/枚举类型——`RunDefinition.status` 一直是纯 `str`（从 5B-6 引入 `interrupted`/`failed` 开始就是这样），合法值靠代码里几个集合/字符串比较来约束（例如 `RESUMABLE_STATUSES = {"in_progress", "interrupted"}`），不是靠类型系统。`awaiting_review`/`approved`/`rejected` 延续的是同一种风格，没有为此新增类型层。

### 错误分类（`src/run_errors.py`）

`RunService` 抓到 `LLMAgentRunExecutor.execute()` 抛出的异常后，用 `classify_error()` 分成 6 类，每类有默认的可重试性：

| 分类 | 可重试 | 触发场景 |
|---|---|---|
| `LIMIT_EXCEEDED` | 是 | `LLMRunLimitError`（`max_total_tokens`/`max_tool_rounds` 超限），调大配置或减少任务范围后可重试 |
| `PROVIDER_ERROR` | 是 | `LLMRateLimitError`/`LLMConnectionError`/`LLMProviderError`，多是网络抖动或 Anthropic 侧暂时故障 |
| `INTERRUPTED` | 是 | 进程被杀/崩溃导致 Run 卡在 `in_progress`——不是任务逻辑本身失败，由 `resume` 检测到后设置，不经过 `classify_error()` |
| `TOOL_ERROR` | 是（默认） | 预留分类：目前 `ToolExecutor.execute()` 从不让异常向上传播（永远转成失败态 `ToolResult`），所以这条分类暂时没有实际触发路径 |
| `CONFIGURATION_ERROR` | **否** | `LLMAuthenticationError`/`LLMConfigurationError`/`LLMPermissionError`——API Key、权限、账户配置问题，需要人先修好 |
| `INTERNAL_ERROR` | **否** | 其它所有未识别异常（包括 `LLMRequestError`）——兜底分类，需要先排查代码/请求本身的问题 |

`retryable=False` 的分类会把 Run 标记为 `failed`；`retryable=True` 的标记为 `interrupted`。

### 恢复：`resume` 命令

```bash
python -m src.main resume <run-id>
```

流程（`RunService.resume()`）：

1. 按 `run_id` 反查它属于哪个 Task（扫描所有 Task 下的 `runs/` 目录，因为 `run_id` 不含 Task 信息）。
2. 只有状态是 `in_progress` 或 `interrupted` 的 Run 才允许恢复；`completed`/`failed` 会直接报错。
3. 如果状态还是 `in_progress`——说明执行进程从没机会把终态写回磁盘（典型的"进程被杀"场景）——先把它标记为 `interrupted`。
4. **不会复用同一个 `run_id` 重跑**：创建一个全新的 Run（`retry_of` 指向旧 Run，复用旧 Run 的 `input.md` 原文），`task.json` 的 `current_run_id`/`run_count` 指向新 Run。
5. 立即对新 Run 发起一次真正的执行（等价于对新 Run 调 `RunService.execute()`），成功/失败的打印格式和 `run` 命令一致。

每个 Run 只代表一次执行尝试，`retry_of` 链可以一路追溯到最初那次尝试，工具调用结果和 token 统计不会跨尝试混在一起。`run <task-id>` 现在也会拒绝对状态不是 `in_progress` 的 Run 直接重跑，报错里会提示改用 `resume`（相关已知限制见文末"已知限制 / 待办"）。

`awaiting_review`/`approved`/`rejected` 都**不在** `RESUMABLE_STATUSES` 里——`awaiting_review` 不是崩溃，而是执行成功但在等人决定，`resume` 对它们一律报错（和 `completed`/`failed` 一样，只是错误提示文案目前还是通用的"cannot be resumed"，还没针对"这个 Run 该用 review 而不是 resume"专门改文案，算是已知的小体验缺口）。

### 人工审核：`ChangeSnapshot` 与 `review` 命令

`RunService.execute()` 在 Run 正常执行完之后（写完 `output.md`/`summary.md`，还没决定最终 `status` 之前），会额外做两件事：

1. 用 `ChangeSnapshotBuilder`（`src/review/change_snapshot_builder.py`）从这次 Run 的 `events.jsonl` 里提取一个 `ChangeSnapshot`（`src/review/change_snapshot.py`）：`changed_files`（`file_mutation` 事件的 `path`，去重、保留首次出现顺序）、`mutation_count`（`file_mutation` 事件的**原始**条数，不去重——同一个文件改 3 次和改 3 个文件各一次，这两种情况值得区分）、`test_results`（`tool_result` 事件里 `name == "run_test"` 的那条，取 `exit_code`/`timed_out`，多次调用取最后一次）、`diff_path`（如果 Run 目录下已经有 `diff.patch` 就记路径，否则 `null`——**这一步不生成 diff 内容**，diff 生成本身还没做）。
2. 把这个 snapshot 存成 Run 目录下的 `change_snapshot.json`（`src/review/snapshot_repository.py` 的 `SnapshotRepository`）。**这一步是关键**：`review` 命令看到的是 Run 结束那一刻的快照，不是重新扫一遍当前仓库状态——如果之后人手动改了代码，`review` 显示的内容不会跟着变。

然后用 `requires_review()`（`src/review/review_policy.py`）决定这次 Run 是 `completed` 还是 `awaiting_review`：

```python
def requires_review(*, agent_id: str, snapshot: ChangeSnapshot) -> bool:
    if agent_id != "agent-coder":
        return False
    return snapshot.mutation_count > 0
```

也就是只有 `agent-coder` 产生了至少一次文件改动的 Run 才需要审核；`agent-general`（本来也没有写权限）和没有实际改动的 Run（比如只是读代码、跑了下测试）都直接 `completed`。`run.json` 的 `metadata` 里始终会记 `review_required`/`changed_files`（不管要不要审核都记，不是只在需要审核时才写），方便以后不用重新解析 `events.jsonl` 就知道"这个 Run 当初为什么停在这里"。

审核命令：

```bash
python -m src.main review <run-id>
```

```text
Run: run-030

Status:
awaiting_review

Changed files:
- src/main.py
- tests/test_main.py

Mutations:
3

Tests:
run_test:
  exit_code: 0
  timed_out: False

Diff:
(no diff recorded)

AI Summary:
Not generated yet.

Approve? [y/N]:
```

- 如果这个 Run 从没产生过 `change_snapshot.json`（比如是 5C-4 上线之前跑的历史 Run），会打印"No change snapshot recorded for this run."然后直接返回，不会报错崩溃。
- 只有当前状态是 `awaiting_review` 时才会出现 `Approve? [y/N]:` 提示；已经 `approved`/`rejected` 或本来就 `completed` 的 Run，看完报告就结束，不会再问一遍。
- 输入 `y`/`yes` → `RunService.decide_review(run_id, approved=True)` → 状态变 `approved`；输入 `n`/`no`/`reject` → 状态变 `rejected`；其它任何输入（包括直接回车）→ 不做任何状态变更，Run 继续留在 `awaiting_review`，可以以后再审。
- `ReviewReport`（`src/review/review_report.py`：`run_id`/`summary`/`changed_files`/`risks`/`approved`）目前 `summary`/`risks` 恒为 `None`/`[]`——`ReviewService.build_report()`（`src/review/review_service.py`）故意设计成纯函数、不做任何 I/O，这样以后接一个真正的 Reviewer Agent 去填 `summary`/`risks` 时，不需要碰这一层的接口。

`src/review/NOTES.md` 记了一个已知的未来演化点：`ChangeSnapshot.test_results` 现在是"按工具名存一条结果"，多次调用同一个测试工具会互相覆盖；如果以后一次 Run 需要跑多个不同测试命令并且都要保留结果，这个字段的形状需要从 dict 换成 list。现在不改，只是先记下来。同一份文件还记了一次预 5C-5 的架构自查（`review/` 没跟随 `tools/` 已经建立的 `domain`/`services` 分层规范、`RunService` 职责在变多、`review_policy.requires_review()` 硬编码了 `"agent-coder"` 这个 agent id 而不是按能力判断）——都只是记录，没有据此改代码。

### 查询与诊断：`runs`/`inspect` 命令

前面这些命令（`run`/`resume`/`review`）都会**改变** Run 的状态，是"command side"。5C-5 加了一条纯只读的"query side"，专门用来回答"发生了什么"，不改任何东西：

```
events.jsonl
      │
      ▼
EventRepository.load_events()   # 逐行读 JSON，缺文件/空文件返回 []，缺 "type" 字段 fallback 成 "unknown"
      │
      ▼
list[RunEvent]                  # src/domain/events/run_event.py，纯数据：event_type/timestamp/run_id/data（data 保留完整原始 payload）
      │
      ▼
TimelineBuilder.build()         # 只做包装，不排序、不重新解释
      │
      ▼
RunTimeline(run_id, events)
```

`RunQueryService`（`src/run_query_service.py`）是这条链路的入口，和 `RunService` 是刻意分开的两个类——`RunService` 执行/改状态，`RunQueryService` 只读，两者都依赖同样的 `TaskRepository`/`RunRepository`，但互不调用对方的方法（`RunQueryService` 自己重新实现了一个几行的"按 run_id 反查 task"逻辑，没有复用 `RunService` 里那个私有方法，这是有意的，query side 不应该依赖 command side）。

```bash
# 列出所有 Task 下的所有 Run
python -m src.main runs

# 查看单个 Run 的时间线/变更/测试结果
python -m src.main inspect <run-id>
```

```text
$ python -m src.main inspect run-026
Run: run-026
Task: task-20260713-001
Agent: agent-general

Status:
completed

Timeline:
1. llm_response
2. tool_call list_files
3. tool_result list_files
4. llm_response
5. tool_call read_file
6. tool_result read_file
7. llm_response
8. run_completed

Changes:
(none)

Tests:
(none)
```

- `runs` 每一行的"Changes: N files"直接读 `run.json` 里 `metadata.changed_files`（5C-4C 起 `RunService.execute()` 就一直在存这个字段），不会为了列表页面去逐个 Run 加载 `ChangeSnapshot`。
- `inspect` 组合三样东西：`run.json`（状态/agent）、`RunTimeline`（事件时间线）、`ChangeSnapshot`（有就显示，没有就显示"(none)"）——三者中任意一个缺失（没有 `events.jsonl`、没有 `change_snapshot.json`）都不报错，这对 5C-4 之前的历史 Run（比如 `task-20260713-001` 早期几十个 Run）尤其重要，它们连 `events.jsonl` 都没有。
- Timeline 每一行的展示格式（`tool_call read_file`、`file_mutation patch` 这种）是 `src/cli/run_display.py` 里做的——这是特意设计的：`RunEvent`/`RunTimeline` 这两层保持"哑"，不做任何解释，把"怎么显示"这件事完全交给一个独立的展示层，以后 Web UI/Discord bot/API 要复用同一份查询逻辑时，不需要重新解析 `events.jsonl`，也不用继承 CLI 的打印格式。
- **已知限制**：真实的 `events.jsonl` 里从来没有出现过 `timestamp` 字段（`llm_executor.py` 用 `round` 排序，不是墙钟时间），所以 `RunEvent.timestamp` 目前恒为 `None`——Timeline 现在完全靠 `events.jsonl` 本身的 append 顺序（`TimelineBuilder` 不排序，原样保留读取顺序）。
- `inspect <run-id>` 和 `resume`/`review` 共享同一个"按 run_id 反查 task"的已知限制：`run_id` 只在单个 Task 内保证唯一，跨 Task 撞号时会解析到（按目录字母序）第一个匹配的 Task——不是这次新引入的问题。

## 架构分层

```
src/
├── models.py              # 领域模型：TaskDefinition / RunDefinition / AgentDefinition / RunExecutionContext / RunExecutionResult（纯 dataclass，from_dict/to_dict 做校验）
├── repositories.py        # 持久化层：读写 JSON/Markdown/JSONL 文件（没有数据库，任务/运行数据就是 tasks/ 目录下的文件树）
├── execution.py           # RunExecutor 协议（Protocol）：execute(context) -> RunExecutionResult
├── context_builder.py     # 把 Task+Run+Agent 拼成一份带项目快照的 RunExecutionContext
├── run_service.py         # 编排一次 Run 的完整生命周期：加载→校验→执行→落盘→标记完成/interrupted/failed；execute()/resume() 都返回 RunServiceResult，失败时抛 RunExecutionFailedError
├── run_query_service.py   # RunQueryService（5C-5）：只读的 query side，list_runs()/inspect_run()，不改任何状态
├── run_errors.py          # 错误分类：classify_error() 把异常映射到 6 类 RunErrorCategory，is_retryable() 给出默认可重试性
├── executor_factory.py    # 按 EXECUTION_MODE 组装对应的 RunExecutor（simulated / llm）
├── simulated_executor.py  # 确定性占位执行器
├── llm_executor.py        # LLMRunExecutor：真正的多轮工具调用循环，返回 LLMRunResult
├── llm_agent_run_executor.py  # LLMAgentRunExecutor：把 Task/Run/Agent 的 RunExecutionContext 接入 LLMRunExecutor 的适配层
├── run_events.py          # RunEventSink 协议 + Null/InMemory/Jsonl 三种实现，events.jsonl 的实时写入机制
├── llm/                   # Provider 无关的请求/响应类型 + Anthropic 具体实现
│   ├── base.py             # LLMProvider 协议：complete(request) -> response
│   ├── types.py            # LLMRequest/LLMResponse/内容块（text/thinking/tool_use）
│   ├── anthropic_provider.py
│   └── exceptions.py       # 细分的 LLM*Error 异常层级
├── domain/tools/           # 工具调用的领域类型：ToolDefinition / ToolCall / ToolResult
├── domain/events/          # 运行事件的领域类型（5C-5）
│   ├── run_event.py               # RunEvent：event_type/timestamp/run_id/data（data 保留完整原始 payload，不裁剪）
│   ├── event_repository.py        # EventRepository：把 events.jsonl 逐行读成 list[RunEvent]，缺文件返回 []
│   ├── timeline.py                 # RunTimeline：run_id + events，纯包装
│   └── timeline_builder.py         # TimelineBuilder：list[RunEvent] -> RunTimeline，不排序、不重新解释
├── cli/                    # CLI 展示层（5C-5），和查询/执行逻辑分开，纯函数（输入数据，输出字符串，不 print）
│   └── run_display.py             # format_run_list() / format_run_inspection()
├── review/                # 人工审核层（5C-4）
│   ├── change_snapshot.py         # ChangeSnapshot：一次 Run 的变更事实（changed_files/mutation_count/test_results/diff_path）
│   ├── change_snapshot_builder.py # 从 events.jsonl 构建 ChangeSnapshot
│   ├── snapshot_repository.py     # 把 ChangeSnapshot 存/取到 Run 目录下的 change_snapshot.json
│   ├── review_policy.py           # requires_review()：决定一个 Run 是 completed 还是 awaiting_review
│   ├── review_report.py           # ReviewReport：summary/risks 目前是占位，留给未来的 Reviewer Agent
│   ├── review_service.py          # ChangeSnapshot -> ReviewReport 的纯转换，无 I/O
│   └── NOTES.md                   # 记录暂不实现、但未来可能要做的设计演化点
└── services/tools/         # 工具调用的服务层
    ├── tool_executor.py     # 统一调度
    ├── tool_policy.py       # 策略加载与校验（Agent 能不能用某个工具）
    ├── test_policy.py       # run_test 的命令白名单加载与校验（run_test 能跑哪些命令）
    ├── test_runner.py       # TestRunner：受限 subprocess 执行层（shell=False/cwd/timeout/输出截断）
    ├── path_guard.py        # 仓库路径边界防护
    ├── file_writer.py       # write_file/patch_file 共享的写入内核（sha256 + 原子替换）
    ├── git_command.py       # git 子进程调用的公共封装
    └── handlers/             # 七个具体工具的实现
```

上面这棵树覆盖的是 5C 阶段（工具调用 + 审核 + 观测）的模块；5D/5E 新增的编排、规划、恢复相关模块单独整理成了这几个目录（各自的职责见前面对应章节，不在这里重复展开整棵树）：

```
src/
├── agent_registry.py / message_router.py / message_routing_errors.py   # Agent 发现 + 消息投递（5D-1/5D-2）
├── task_plan.py / task_dependency_resolver.py / task_scheduler.py      # TaskPlan 模型 + 依赖排序 + 调度（5D）
├── retry_policy.py / retry_manager.py / retry_decision.py / retry_result.py
├── failure_classifier.py / failure_retry_classifier.py / step_execution_result.py
├── manager_agent.py                                                     # ManagerAgent：request -> TaskPlan
├── execution_checkpoint.py / execution_checkpoint_repository.py         # 恢复用的检查点（5E-5）
├── recovery_*.py                                                        # RecoveryOrchestrator/Planner/Executor/Plan/Action
├── runtime_approval_*.py                                                # 执行期人工审批闸门（5E-5）
├── agents/                # Task-Scoped Agent 生命周期：AgentTemplate/TaskAgent/Registry/AssignmentService/CleanupService/TeamLifecycle
├── context/                # Static Context Optimization：ContextSelector/ContextTrimmer/ContextBudget（含 history/ 子目录，即 History Compression）
└── planning/               # Planner 协议、RuleBasedPlanner/ClaudePlanner、PlanValidator、PlanReview/Approval、PlanRepairLoop、PlanService/PlanExecutionService、TaskCompletionService、TaskPlanResumeService
```

配置和 Agent 定义：

```
agents/<agent-id>/
├── agent.json           # 名称、角色、默认模型、资源限制、能力标签
├── system-prompt.md     # 该 Agent 专属的 system prompt
└── tool-policy.json      # 该 Agent 的工具权限策略

src/config/
└── test_policy.json      # run_test 的命令白名单（不区分 Agent，是平台全局配置）

tasks/<task-id>/
├── task.json             # 状态、当前 Run、Run 计数、完成标准
├── background.md         # 跨 Run 共享的累积背景
├── plan.json              # PlanRecord：TaskPlan + status（pending/approved/rejected/executed），5D-6B-1
├── approval.json          # ApprovalRecord：plan 命令的人工审批决定（approve-plan/reject-plan）
├── runtime_approval.json  # RuntimeApprovalRequest：执行期 BLOCKED 失败的人工审批闸门（5E-5，与上面 approval.json 是两个独立文件）
├── checkpoint.json        # ExecutionCheckpoint：恢复用的执行进度快照（5E-5，目前无 CheckpointWriter，靠手工构造）
└── runs/run-NNN/
    ├── run.json               # 状态（in_progress/completed/awaiting_review/approved/rejected/interrupted/failed）、时间戳、（可选）retry_of/error_category/error_message/retryable/context_files/review_required/changed_files
    ├── input.md                # 本轮的具体指令
    ├── output.md                # 模型的完整回答（含累计 token 用量等元信息）
    ├── summary.md                # 简短摘要（含累计 token/轮次/工具调用次数）
    ├── events.jsonl              # 每轮 LLM 调用/工具调用的结构化审计记录，实时追加写入（llm 模式才有）
    └── change_snapshot.json      # ChangeSnapshot 的持久化（changed_files/mutation_count/test_results/diff_path），review 命令读这个而不是重新计算
```

## 快速开始

```bash
# 1. 建虚拟环境、装依赖
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 测试用的 pytest 目前不在 requirements.txt 里，需要单独装
.venv/bin/pip install pytest

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env：至少要在 llm 模式下填 ANTHROPIC_API_KEY

# 3. 查看所有任务
.venv/bin/python -m src.main list

# 4. 执行某个任务当前的 Run
.venv/bin/python -m src.main run <task-id>

# 4b. 恢复一个卡在 in_progress/interrupted 的 Run（创建新 Run 重试）
.venv/bin/python -m src.main resume <run-id>

# 4c. 查看一个 awaiting_review 的 Run（改动了什么/测试结果），并 approve/reject
.venv/bin/python -m src.main review <run-id>

# 4d. 列出所有 Task 下的所有 Run / 查看单个 Run 的时间线
.venv/bin/python -m src.main runs
.venv/bin/python -m src.main inspect <run-id>

# 5. 跑测试
.venv/bin/python -m pytest tests/
```

**环境变量一览**（见 `.env.example`，均有默认值，`llm` 模式下 `ANTHROPIC_API_KEY` 必填）：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `EXECUTION_MODE` | `simulated` | `simulated` 或 `llm` |
| `LLM_PROVIDER` | `anthropic` | 目前只支持 `anthropic` |
| `ANTHROPIC_MODEL` | `claude-sonnet-5` | |
| `LLM_TIMEOUT_SECONDS` | `60` | |
| `LLM_MAX_RETRIES` | `2` | |
| `LLM_MAX_TOKENS` | `4096` | 单轮回复的输出上限，建议调到 16000+ 给 thinking 留出空间 |
| `LLM_MAX_TOOL_ROUNDS` | `8` | 单次 Run 最多允许几轮工具调用 |
| `LLM_MAX_TOTAL_TOKENS` | `100000` | 单次 Run（含所有工具调用轮次）的总 token 上限 |
| `DEBUG_LOG_FULL_OUTPUT` | `false` | `true` 时 `events.jsonl` 里的 `tool_result` 事件会额外带上工具的完整输出（默认只记 `output_chars`/`truncated`，不记全文） |
| `TEST_POLICY_PATH` | `src/config/test_policy.json` | 相对 `project_root` 的路径，指向 `run_test` 的命令白名单文件 |

## 测试

```bash
.venv/bin/python -m pytest tests/ -v
```

当前 996 个测试（5C 阶段 314 个之外，5D 任务编排/人工审批、5E Task-Scoped Agent、Claude 结构化规划、计划自修复、执行恢复与运行时审批、Static Context Optimization 这几块新增的测试占了大头，见上面各自章节末尾列出的测试文件），5C 阶段覆盖：`src/domain/events/`（`tests/domain/events/`：`RunEvent`/`EventRepository`——含读取真实历史 `events.jsonl`/`TimelineBuilder`，共 18 个测试）、`RunQueryService`（`tests/test_run_query_service.py`：跨 Task 汇总 `list_runs()`、`inspect_run()` 的找到/找不到、缺 events/缺 snapshot 时的优雅降级、真实持久化 snapshot 的加载）、`src/cli/run_display.py`（`tests/cli/`：Run 列表/Timeline/变更/测试结果的纯文本渲染，含复数形式、空状态）、工具的路径防护（含 `write_file`/`patch_file` 专用的 `resolve_repository_write_path()`）、七个具体工具的正确性（`list_files`/`read_file`/`git_status`/`git_diff`/`write_file`/`patch_file`/`run_test`）、共享写入内核 `file_writer.py`、`run_test` 的命令白名单加载校验（`test_policy.py`）与受限 subprocess 执行层（`test_runner.py`：`shell=False`、超时、输出截断、cwd 隔离）、`ToolExecutor` 的调度/策略/异常兜底逻辑（含 `duration_ms` 计时）、`ToolPolicy`/`TestPolicy` 的 JSON 解析校验、`AnthropicProvider` 的请求构造与响应解析（mock 掉真实网络请求）、`RunEventSink` 实现（`tests/test_run_events.py`：内存/JSONL/丢弃三种 sink，JSONL 的 unicode 与 truncate 行为）、`LLMRunExecutor` 的多轮循环行为（工具失败传播、轮次超限、累计 usage/events、中途异常仍保留已发生事件、debug 开关、`file_mutation` 审计事件的生成/排除条件）、`LLMAgentRunExecutor` 适配层（mock `LLMProvider`/`AgentRepository`，真实 `ToolExecutor`/`RunRepository`，含 events.jsonl 与 debug 模式，见 `tests/test_llm_agent_run_executor.py`）、`executor_factory.py` 的 Agent 能力隔离（`tests/test_executor_factory.py`：合成 policy + 加载真实 `agents/agent-general`/`agents/agent-coder` 两份 `tool-policy.json` 双重验证）、错误分类（`tests/test_run_errors.py`：6 类 `RunErrorCategory` 与默认可重试性）、`RunService`（`tests/test_run_service.py`：成功路径的 `RunServiceResult`、simulated 风格的空 usage 字段、`LIMIT_EXCEEDED`→`interrupted` 与未分类错误→`failed` 两种失败路径、`resume()` 的崩溃检测/新建 Run/`retry_of` 链接/拒绝重跑非法状态、`awaiting_review`/`approved`/`rejected` 状态转换、`get_run()`/`decide_review()`）、`src/review/` 人工审核层（`tests/review/`：`ChangeSnapshot`/`ChangeSnapshotBuilder`/`SnapshotRepository`/`review_policy.requires_review()`/`ReviewService`/`ReviewReport`，共 26 个测试）。

> 注意：`pytest` 需要在装了 `anthropic`/`python-dotenv` 的同一个环境（`.venv`）里跑，否则涉及 Anthropic Provider 的测试会因为 `ModuleNotFoundError: No module named 'anthropic'` 而无法 collect。

### 如何确认一次真实工具调用确实跑通了

单元测试用的都是 `FakeProvider`，能证明 `LLMRunExecutor`/`ToolExecutor` 自身逻辑没问题，但**证明不了**某一次对真实 Anthropic API 的 Run 确实发生了工具调用——模型的最终回答文本本身不是可信证据：它完全可能声称"我调用了 list_files"却其实没调用，或者调用失败后编一个结果。下面是几种由弱到强的验证方法（`tasks/task-20260713-001` 的 run-009/011/014 都是用这套方法验证过的真实案例）：

1. **内容交叉核对**：把模型声称的工具输出，跟自己手动跑一遍的结果对比。细节对得越精确（比如 `.git` 被排除、隐藏文件的取舍），越能确认不是编的。最简单，跑完 Run 直接能做，但对于模型靠常识就能蒙对的内容（比如"README 讲了什么"）说服力有限。

   ```bash
   # 对比 list_files 声称的根目录列表
   ls -a .

   # 对比 read_file 声称读到的内容（换成实际路径/行数）
   sed -n '1,40p' README.md
   ```

2. **设计"强制依赖"任务**：让后一步工具调用的具体参数必须依赖前一步工具调用的真实返回结果，且这个结果是模型不可能提前猜到的（例如"列出 `X/` 目录，读取按字母序排第 N 个的文件"——`N` 要跨过运行时才存在的 `__pycache__/` 这类目录）。如果模型的最终答案精确匹配这种"不可能靠猜"的细节，就是硬证据。

   ```bash
   TASK_ID=task-20260713-001
   RUN_ID=run-XXX   # 换成下一个未用过的编号

   # 1) 建 run 目录
   mkdir -p "tasks/$TASK_ID/runs/$RUN_ID"

   # 2) 写 input.md：第二步的目标必须依赖第一步 list_files 的真实返回
   cat > "tasks/$TASK_ID/runs/$RUN_ID/input.md" <<'EOF'
   请先调用 list_files 查看 src/services/tools/handlers/ 目录（不要递归）。
   然后按名称字母顺序数出第 3 个条目（如果是目录就顺延到下一个普通文件），
   用 read_file 读取该文件前 15 行。你必须依据 list_files 的真实返回内容确定
   文件名，不能凭猜测。最后用中文说明这个文件实现了什么功能。
   EOF

   # 3) 写 run.json（沿用同目录下其它 run.json 的字段格式，status 设为 in_progress）

   # 4) 把 task.json 的 current_run_id 指向这个新 run，run_count 加一

   # 5) 跑真实 LLM
   EXECUTION_MODE=llm .venv/bin/python -m src.main run "$TASK_ID"
   ```

3. **临时加 round 级别日志**：在 `LLMRunExecutor.execute()`（`src/llm_executor.py`）的循环里临时加一行 `print`，把每一轮的 `response.stop_reason` 和 `[c.name for c in response.tool_calls]` 打出来。这是最直接的证据——`stop_reason`/`tool_calls` 是 Anthropic API 返回的原始字段，不经过模型自己的"复述"，不可能被模型编造。

   ```python
   # 在 LLMRunExecutor.execute() 的 while True 循环里，
   # response = self._provider.complete(current_request) 这一行之后加：
   print(
       f"[TEMP LOG] round={round_number} "
       f"stop_reason={response.stop_reason} "
       f"tool_calls={[c.name for c in response.tool_calls]}"
   )
   # round_number 需要在循环外初始化为 0，循环开头 += 1
   ```

   ```bash
   # 加完之后跑同一个 Run，日志会直接打在终端上
   EXECUTION_MODE=llm .venv/bin/python -m src.main run "$TASK_ID"
   ```

   验证完之后记得把这几行删掉，不要留在主分支里。

4. **Anthropic 控制台**：https://console.anthropic.com 的 Usage/Logs 页面能看到这个 API Key 每次请求的真实次数、是否带了 `tools`、返回是否含 `tool_use` block——独立于本项目代码之外的第三方证据。

最可靠的组合是 **2 + 3**：设计一个必须依赖上一步真实结果才能回答对的任务，再用临时日志确认轮次和工具名。单看 `output.md` 的文字内容只能算弱证据。

`patch_file` 也用这套方法做过一次真实 API 验收（`tasks/task-patch-test` 的 run-001）：任务要求 `agent-coder` 把 `sandbox/hello.py` 里的 `print("Hello")` 改成 `print("Hello Agent")`，明确要求必须用 `patch_file`、不能用 `write_file`。真实调用序列是 `read_file` → `patch_file`（`old_text` 用了 `"def greet():\n    print(\"Hello\")"` 整块而不是只匹配 `"Hello"`，避免歧义匹配）→ `read_file` 自我验证 → 结束。`events.jsonl` 里全程没有出现 `write_file`，且产生了 `file_mutation`（`operation: "patch"`）事件，文件内容与预期完全一致。

`read_file` → `patch_file` → `run_test` 串成一个完整的"自主修复循环"也做过真实 API 验收（`tasks/task-run-test-loop` 的 run-001）：`sandbox/calculator.py` 里故意写错了 `add()`（`return a - b`），`sandbox/test_calculator.py` 断言 `add(2, 3) == 5` 因此失败；任务描述只说"有个测试失败了，修好它"，**没有告诉模型答案**。真实调用序列是 `read_file`（先后读了 `calculator.py` 和 `test_calculator.py`）→ `patch_file`（`old_text`/`new_text` 各是完整的两行函数体）→ `run_test(test_name="unit")`，`ToolResult.metadata` 里 `exit_code: 0`，随后模型才给出最终总结。这次只用了一轮 `patch_file` 就修对了，所以没有观察到"改错了、`run_test` 报失败、再改一次"这种真正的重试路径——如果要验证重试路径，需要设计一个模型第一次大概率会改错的任务，目前还没有这样的案例。

## 任务编排与人工审批：Manager Agent → TaskPlan → 调度执行（5D）

在"一个 Run 执行一次工具调用循环"之上，还有一层更高的编排：一个 Task 先被拆成一份 `TaskPlan`（多个带依赖关系的 `TaskStep`，每步指定由哪个 Agent 执行），经过校验、人工审批，才会真正进入调度执行，每一步还可能失败重试。这条链路目前**只处理"分给谁做、按什么顺序做、失败了要不要再试一次"，还不负责真的把每个 `TaskStep` 变成一次 LLM 工具调用 Run**——那是 `TaskPlanExecutor`/`AgentRuntimeFactory` 这一层的事，编排层只依赖它暴露的 `execute_step(step, task_id) -> str`（失败就 raise）这个窄接口。

```text
用户请求
   │
   ▼
ManagerAgent.plan()          # 委托给一个 Planner（RuleBasedPlanner / 未来的 ClaudePlanner）
   │
   ▼
TaskPlan(task_id, steps: [TaskStep(step_id, agent_id, description, depends_on)])
   │
   ▼
PlanValidator.validate()     # UNKNOWN_AGENT / AGENT_NOT_IN_TASK / MISSING_DEPENDENCY / DEPENDENCY_CYCLE
   │
   ▼
PlanReviewService.create_review()   # 确定性文本摘要，不是模型生成
   │
   ▼
人工：approve-plan / reject-plan
   │
   ▼ (approved)
ApprovedPlanExecutor.execute()      # 唯一同时认识 Planning 层和 TaskScheduler 的桥
   │
   ▼
TaskDependencyResolver.resolve()    # TaskPlan -> 若干"轮"（wave），同轮内的 step 互不依赖
   │
   ▼
TaskScheduler.run()                 # 逐轮执行：轮内用线程池并行，轮间串行
   │       每个 step 经 RetryManager 按 RetryPolicy 重试；
   │       依赖没成功的 step 直接标 SKIPPED，不会被派发
   ▼
list[StepExecutionResult]           # SUCCESS / FAILED / SKIPPED，FAILED 带分类后的 ExecutionFailure
```

- **Agent 发现与消息投递**：`AgentRegistry`（`src/agent_registry.py`）只是 `AgentRepository` 之上一层薄封装，回答"平台里有哪些 Agent"；`MessageRouter`（`src/message_router.py`）回答"这条消息现在能不能送到某个 Agent 手上"——`send()` 会先查 `TaskAgentRegistry.list_agents(message.task_id)`，确认 `receiver_id` 确实是**这个 Task 当前指派**的 Agent（不是"平台里存在"就够），再去分发；哪怕路由器内部还持有某个 Agent 的 handler 实例，只要 `TaskAgentRegistry` 说它已经不再属于这个 Task，也会被 `AgentNotAssignedToTaskError` 拒绝——这是防止"陈旧 handler 被当成授权凭证"的第二道执行期防线（第一道是下文 Task-Scoped Agent 架构里 `AgentRuntimeFactory` 本身只构建当前 Task 指派的 handler）。
- **TaskPlan 模型**（`src/task_plan.py`）：`TaskStep(step_id, agent_id, description, depends_on: list[str])` + `TaskPlan(task_id, steps)`，纯 dataclass，`depends_on` 默认空列表。
- **依赖解析**：`TaskDependencyResolver.resolve()`（`src/task_dependency_resolver.py`）把 `depends_on` 图拓扑排序成"轮"（`list[list[TaskStep]]`）——每一轮内的 step 互不依赖，是并行调度的最小单位；图里有环则抛 `CyclicDependencyError`。
- **调度与重试**：`TaskScheduler.run(plan)`（`src/task_scheduler.py`）逐轮执行，轮内用 `ThreadPoolExecutor` 并行派发、轮间串行（后一轮可能依赖前一轮的结果）；某个 step 的依赖没有成功（`FAILED`/`SKIPPED` 都算），这个 step 直接记 `SKIPPED`，根本不会被派发，且这个"没成功"会向下游传递。真正执行一次尝试交给 `RetryManager.execute()`（`src/retry_manager.py`），按注入的 `RetryPolicy`（`src/retry_policy.py`，目前只有一个字段 `max_attempts`，默认 1）重试；每次真实抛出的异常先经 `FailureClassifier.classify()`（`src/failure_classifier.py`）分类成 `ExecutionFailure`（`TEMPORARY_ERROR`/`PLAN_ERROR`/`BLOCKED`/`FATAL`），再由 `FailureRetryClassifier`（`src/failure_retry_classifier.py`）判断这一类失败值不值得重试（目前只有 `TEMPORARY_ERROR` 会重试）——"重试几次"（`RetryPolicy`）和"这次失败值不值得重试"（`FailureRetryClassifier`）是两个独立问题，谁都不覆盖谁。
- **从请求到计划**：`Planner`（`src/planning/planner.py`）是一个结构化 `Protocol`：`create_plan(request, task_id, context: TaskPlanningContext | None) -> TaskPlan`。默认实现 `RuleBasedPlanner`（`src/planning/rule_based_planner.py`）纯关键词匹配（"研究"+"实现"之类的组合触发不同形状的计划），不做真正的语言理解，只是用来证明 Planner 这层接口能产出带依赖关系的多步计划；它完全忽略传入的 `context`。
- **计划校验**：`PlanValidator.validate(plan)`（`src/planning/plan_validator.py`）在计划真正被调度前挡一道：`UNKNOWN_AGENT`（`agent_id` 在 `AgentRegistry` 里根本不存在）、`AGENT_NOT_IN_TASK`（Agent 是真的，但没有指派给这个 Task——两种错误分开报，是为了让后面的自动修复知道具体错在哪一类）、`MISSING_DEPENDENCY`（`depends_on` 指向不存在的 `step_id`）、`DEPENDENCY_CYCLE`。只产出 `PlanValidationResult`（`errors: list[ValidationError]`，每条错误目前都标 `repairable=True`），不自己拒绝或修复计划——校验结果交给下一层决定怎么处理。
- **人工审批闭环**：`PlanReviewService.create_review(plan)`（`src/planning/plan_review_service.py`）跑一遍校验，把 `TaskPlan` + `PlanValidationResult` 拼成一份**确定性字符串摘要**（不是模型生成——这是人工审批的安全边界，摘要必须能从计划本身精确复现，不能每次调用结果都不一样）。`PlanApprovalService.approve()/reject()`（`src/planning/plan_approval_service.py`）故意不检查 `validation.valid`——校验没通过的计划人也可以硬批，因为决定权在人，不在校验器。`PersistentApprovalService`（`src/planning/persistent_approval_service.py`）在这之上加一层磁盘持久化（`ApprovalRecord`），使得"计划创建"和"人工批准"可以发生在完全不同的进程/不同的时间点，中间不需要任何进程常驻。
- **CLI**：

  ```bash
  # 为一个 Task 生成一份待批准的 TaskPlan（只生成，不执行）
  python -m src.main plan <task-id> "<用自然语言描述这次要做的工作>"

  # 列出所有待审批的计划
  python -m src.main plans

  # 批准并立即执行（成功后如果整份计划都成功，会触发 Task 完成收尾，见下文 5E-4）
  python -m src.main approve-plan <task-id>

  # 拒绝，不执行
  python -m src.main reject-plan <task-id>
  ```

  `approve-plan` 背后是 `PlanExecutionService`（`src/planning/plan_execution_service.py`）——它刻意每次 `execute()` 都重新从磁盘加载 `PlanRecord`/`ApprovalRecord`，重新构建一整条 `MessageRouter`/`TaskPlanExecutor`/`TaskScheduler`/`ApprovedPlanExecutor` 调用链，而不是复用某个常驻实例：`plan` 命令和 `approve-plan` 命令可以是两次完全独立的进程调用（甚至不同天），中间唯一传递的状态就是 `task_id` 对应的磁盘文件。执行结果被聚合成 `PlanExecutionResult`（整份计划是否全部成功），供后续判断 Task 是否可以标记完成。
- **持久化**：`tasks/<task-id>/plan.json`（`PlanRecord`：`task_id`/`plan`/`created_at`/`status` — `pending`/`approved`/`rejected`/`executed`）、`tasks/<task-id>/approval.json`（`ApprovalRecord`：审批决定，和下文运行时审批用的 `runtime_approval.json` 是两个不同的文件，互不覆盖）。

## History Compression（历史压缩，5D-6B-4）

`LLMRunExecutor`（`src/llm_executor.py`）的多轮工具调用循环每一轮都要把完整对话历史重发给 provider——历史越滚越大，每轮成本随之增长。History Compression 是这个循环内置的一层：每轮 provider 调用前，把完整历史（durable，永不截断）压缩成一份更短的"本轮实际发送视图"，同时保留完整历史供后续轮次继续使用。

### 架构

```
LLMMessage[]  (durable，只增不减)
      │
      ▼
MessageGroupBuilder          # src/context/history/message_group_builder.py
      │  把消息切成 INITIAL_TASK / TOOL_EXCHANGE / NORMAL 三类 MessageGroup
      │  （assistant tool_use + 紧跟的 user tool_result 配对成一个原子单元）
      ▼
list[MessageGroup]
      │
      ▼
GroupSelector                # src/context/history/group_selector.py
      │  四段优先级选择，每段都是「从新到旧扫描、不 break、只 continue」：
      │    1) group 0（INITIAL_TASK）——无条件保留，预算再小也不例外
      │    2) PROTECTED 工具交换（apply_patch/write_file/create_file/
      │       delete_file/git_commit）——状态改变类操作优先抢预算
      │    3) 其余非 EVICTABLE 的（NORMAL + 未知工具）——按新旧顺序抢剩余预算
      │    4) EVICTABLE 工具交换（read_file/list_files/search）——最后才轮到
      │  依赖 HistorySizeEstimator（可替换的 token 估算）+
      │       ToolRetentionPolicy（tool_name → PROTECTED/NORMAL/EVICTABLE）
      ▼
GroupSelectionResult(retained_positions)
      │
      ▼
RuleBasedHistoryCompactor    # src/context/history/rule_based_history_compactor.py
      │  把 group position 展平回 message index
      ▼
CompactionPlan(original_count, retained_indices)
      │
      ▼
apply_compaction_plan()      # src/context/history/apply_compaction_plan.py
      │  messages[i] for i in retained_indices —— 纯函数，不修改/不复制原 history
      ▼
本轮 LLMRequest.messages（发给 provider 的，只是一个视图）
```

并行的可解释性支路（不影响上面的决策，只是复述）：

```
messages + groups + retained_positions
      │
      ▼
CompactionReportBuilder      # src/context/history/compaction_report_builder.py
      │  重新跑一遍 ToolRetentionPolicy 分类，标注每个 group 的保留/删除原因
      │  （initial_task / protected_tool / recent_context / budget_limit）
      ▼
CompactionReport  →  events.jsonl 的 "compaction_report" 事件（每轮一条）
```

`LLMRunExecutor` 还会发 `context_usage` 事件（`src/context/context_usage_builder.py`），拆出 `system_prompt_tokens`/`tool_definition_tokens`/`initial_message_tokens`/`history_before_tokens`/`history_after_tokens`/`total_sent_tokens`，可以直接从 `events.jsonl` 里看出某一轮的 token 大头在哪。

### 不变量（都有对应测试，见 `tests/context/history/`）

- **原子性**：一个 `TOOL_EXCHANGE` group（`tool_use` + `tool_result`）永远整体保留或整体删除，绝不拆开半个——`GroupSelector`/`RuleBasedHistoryCompactor` 从不按 message index 操作，只按 group position 操作。
- **initial task 强制保留**：无论预算多小（甚至 0），group 0 永远在保留集合里；预算不够时其余内容会被砍到只剩它。
- **未知工具默认安全**：`ToolRetentionPolicy.classify()` 对没见过的 tool_name（包括孤立 tool_use/tool_result 导致 `tool_name=None` 的情况）返回 `NORMAL`，不会被当成可随意丢弃的 `EVICTABLE`——防止新工具被静默清理。
- **不修改原始历史**：`HistoryCompactor.compact()`/`apply_compaction_plan()` 全程只读，`LLMRunExecutor` 里累积增长的 `messages` 列表永远不会被压缩后的视图覆盖（不会出现 `messages = request_messages` 这种写法）。
- **确定性**：同样的 `messages`/`budget` 输入，`compact()` 多次调用结果完全一致。
- **协议合法性**：即使 `GroupSelector` 的"不 break、只 continue"策略会让保留结果出现不连续的间隔（新算法相对 4B-2 版本的行为变化），重建后发给 provider 的消息序列依然满足 Anthropic 协议——每个保留的 `tool_result` 前面紧跟着 id 匹配的 `tool_use`，历史结尾不会有悬空的未回应 `tool_use`（`test_retained_messages_still_form_a_valid_tool_protocol_sequence`）。

### Benchmark（`benchmarks/history/run_history_benchmark.py`，本地确定性脚本，不打真实 API）

用合成但真实感的 80 轮长历史（每 5 轮一次 `apply_patch`，其余多数是 `read_file`，穿插纯文本轮次），分别用极大预算（等效禁用压缩）和 8000 token 预算（启用压缩）跑同一套真实压缩管线：

```json
{
  "task": "retention_test",
  "rounds": 80,
  "without_compaction": {"input_tokens": 1346682},
  "with_compaction": {"input_tokens": 547226},
  "compression_ratio": 0.5936,
  "broken_tool_pairs": 0
}
```

**压缩比 59.36%，0 个 broken tool pair。** 运行：`python -m benchmarks.history.run_history_benchmark`。

第一版基准（30 轮）压缩比只测出 14.3%——排查后发现是场景设计问题：预算 8000 tokens 时前 18 轮左右历史压根没超预算，压缩根本没被触发，这些"无事可做"的轮次拉低了整体平均值。这本身也是个有用的结论：**History Compression 的收益只在长会话的"稳态期"才体现，短会话不需要它，也不会被它拖慢。**

### ⚠️ Known limitation：它只管历史，不管固定成本

> **History Compression handles dynamic history growth. It does not reduce mandatory static context cost.**

`GroupSelector` 的四段优先级选择，动的是 `TOOL_EXCHANGE`/`NORMAL` 这些**会随轮次增长**的 group。但 group 0（`INITIAL_TASK`）**无条件保留**——它不是一条普通消息，而是 `LLMAgentRunExecutor._build_request()` 拼出来的、内嵌了 `RunContextBuilder.project_snapshot`（静态项目上下文快照）的那条消息。这部分成本：

- **每一轮都原样重发**，跟历史压缩得多干净完全无关；
- 在两次真实 smoke test 中实测占了单轮 token 的大头（"implement a login feature" 任务约 9,431 估算 tokens / 单轮 22,043 真实 tokens；"validation feature" 任务约 31,592 估算 tokens / 单轮 48,669 真实 tokens）；
- 两次真实 run 里，`compaction_report` 事件的 `removed_count` **全程为 0**——history 还没来得及长到超预算，run 就先被 `max_total_tokens`（跨轮累加的 100k 硬顶）打断了。

**所以如果之后有人问"为什么已经有 History Compactor 了，Run 还是报 `Maximum total token limit exceeded`？"——答案就在这里**：这个组件解决的是"对话历史膨胀"问题，不是"静态上下文过大"问题，两者是独立的成本来源。真正压低单轮底线成本需要回到 `RunContextBuilder`/`ContextSelector`/`ContextTrimmer`（`src/context_builder.py` + `src/context/`）那一侧做 Static Context Optimization——这部分现已实现，见下一节。

## Static Context Optimization：ContextSelector / ContextTrimmer

History Compression 只解决"对话历史越滚越大"，不解决"第一轮发的静态项目快照本身就很大"。这部分现在由 `src/context/`（不含 `history/` 子目录，那是上一节的东西）实现，并已经接入 `RunContextBuilder`（`src/context_builder.py`），取代了原来硬编码的固定 5 个文件。

- `ContextSelector`（Protocol）/`RuleBasedContextSelector`：不做语义理解，用关键词重叠打分——从任务描述里抽出长度 ≥3 的词，遍历仓库文件（用 `path_exclusions.is_excluded()` 过滤 `.git`/`.venv`/`__pycache__`/`.env` 等噪音路径），按文件名词干与关键词的双向子串包含关系匹配。一个词都匹配不上时，回退到 `FALLBACK_FILES = ("src/main.py", "README.md")`——刻意不是旧硬编码列表的那 5 个文件。
- `ContextBudget`（`context_budget.py`）：只有 `max_tokens` 一个字段，是"单次请求的静态上下文预算"，和 `llm_executor.py` 里跨轮累加的 `max_total_tokens` 是两个不同维度的限制。
- `ContextTrimmer`（Protocol）/`RuleBasedContextTrimmer`：预算不够时，按 `ContextSelector`给出的顺序从后往前丢整个文件（文件级别裁剪，不做文件内部截断——`ContextFile` 目前还没有内容/token 计数字段）。
- `ContextSizeEstimator`（Protocol）/`RuleBasedContextSizeEstimator`：`len(text) // 4` 的字符数量级估算，不是真正的 tokenizer，而且**只估算快照的元数据**（文件路径、选中理由、项目目录树），不读文件内容——所以裁剪现在是"按文件数量"裁剪，不是真正按 token 精确截断到预算线以内；一份指向几个巨大文件的快照，估算出来的 token 数可能小得离谱。这是已知的下一步改进点。
- `ContextFile`/`ContextSnapshot`（`context_file.py`/`context_snapshot.py`）：纯数据，`ContextSnapshot` = `files: list[ContextFile]` + `project_tree: str`。

这一层解决的是内存记录里长期标记为"已定位根因、未修复"的缺口（no ContextSelector，硬编码 5 个不相关文件）——现在已经修复并接入生产路径，测试见 `tests/context/`（`test_rule_based_context_selector.py`/`test_rule_based_context_trimmer.py`/`test_context_budget.py`/`test_context_builder_integration.py`）。剩余已知限制见文末。

## Task-Scoped Agent 架构（5E-4）

早期设计隐含"Agent 是全局池子，谁都能用"的假设；这一版把"可复用的 Agent 资产"和"这个 Agent 当前属于哪个 Task"拆成两个不同生命周期的概念，冻结在 `docs/architecture/agent_lifecycle_policy.md`，并有 `tests/architecture/test_agent_lifecycle_policy.py` 锁定不变量：

| 概念 | 类 | 生命周期范围 |
|---|---|---|
| `AgentTemplate` | `src/agents/agent_template.py` | 全局、持久、用户创建 |
| `AgentDefinition` | `src/models.py`（已有） | 全局、持久，可被多个 Task 先后复用 |
| `TaskAgent` | `src/agents/task_agent.py` | 单个 Task 内，临时的"成员关系"记录 |
| Runtime Handler（`LLMAgentHandler`） | `src/agent_handlers/llm_agent_handler.py` | 单次执行调用，从不缓存 |

四条锁定的不变量：①`TaskAgent.agent_id == AgentDefinition.id`；②`TaskAgent.template_id == AgentDefinition.template_id`（由 `TaskAgentAssignmentService` 强制，不匹配抛 `AgentTemplateMismatchError`）；③清理隔离——`TaskAgentCleanupService.cleanup(task_id)` 绝不触碰其它 Task 的 `TaskAgent` 记录，也不碰 `AgentDefinition`/`AgentTemplate` 本身；④执行隔离——一个 Runtime Handler 绝不会活得比构建它的那次 `create_handlers(task_id)` 调用更久。

- `TaskAgentRegistry`（`task_agent_registry.py`）：`assign_agent`/`list_agents(task_id)`/`get_agent`/`owner_task_id(agent_id)`/`remove_task_agents(task_id)`，以 `task_id` 为第一层 key，结构上就不可能发生跨 Task 泄漏。
- `TaskAgentTeamState`（`OPEN → LOCKED → RELEASED`，不可逆）与 `TaskAgentTeamLifecycle`：每个 Task 一份状态机；未指派任何 Agent 的 Task 默认 `OPEN`。`PlanService.create_plan()` 会在读取 `TaskPlanningContext` **之前**先 `lock()`，避免"读取团队成员"和"锁定团队"之间出现指派窗口期。
- `TaskAgentAssignmentService.assign(task_id, agent_id, template_id)` 是创建 `TaskAgent` 记录的**唯一合法入口**：检查 Task 存在、团队状态是 `OPEN`、Agent 存在、`template_id` 匹配、这个 Agent 没有被其它 Task 占用（否则抛 `AgentAlreadyAssignedToTaskError`/`AgentAlreadyAssignedElsewhereError`/`TaskAgentTeamLockedError`/`TaskAgentTeamReleasedError`）。
- `TaskAgentCleanupService.cleanup(task_id)`：只有当 `task.status == "completed"`（重新独立检查，不信任调用方传入的状态）才会触发，调用 `team_lifecycle.release()`（`LOCKED → RELEASED`）并清掉这个 Task 的 `TaskAgent` 记录；`AgentDefinition`/`AgentTemplate` 完好保留，可以被指派给下一个 Task。
- `TaskAgentInfo`（`task_agent_info.py`）：给 Planner 看的窄视图（`agent_id`/`role`/`description`/`capabilities`），刻意不包含 `task_id`/状态/`template_id`。

完整生命周期：用户创建 `AgentTemplate` → 创建引用它的 `AgentDefinition` → `TaskAgentAssignmentService.assign()` 生成 `TaskAgent`（团队保持 `OPEN`）→ `PlanService.create_plan()` 锁定团队（`LOCKED`）→ 执行阶段所有 handler 都通过 `AgentRuntimeFactory.create_handlers(task_id)` 现建、Task 范围隔离、绝不缓存 → Task 完成后 `TaskAgentCleanupService.cleanup()` 释放团队并清空该 Task 的 `TaskAgent` 记录，`AgentDefinition`/`AgentTemplate` 本身可以被重新指派给一个全新的 Task。`MessageRouter.send()`（见上一节）是这套结构的第二道执行期防线。

测试覆盖：`tests/agents/`（每个类一份单测）、`tests/integration/test_agent_lifecycle_regression.py`（Template → Definition → Task → Assignment → Lock → Execute → Complete/Fail → Cleanup 全链路，用真实 `AgentRegistry`/`AgentRepository`，会真的写 `agent.json`）、`test_task_agent_assignment_flow.py`、`test_agent_definition_reuse_lifecycle.py`、`test_cross_task_execution_isolation.py`。

## Claude 结构化规划与计划自修复（5E-1 ~ 5E-3）

`RuleBasedPlanner` 只是关键词分支，`ClaudePlanner`（`src/planning/claude_planner.py`）是真正调用模型生成结构化计划的实现，满足同一个 `Planner` Protocol，理论上可以直接替换：

```text
ClaudePlanner.create_plan(request, task_id, context: TaskPlanningContext)
   │
   ▼
PlannerPromptBuilder.build()     # 纯字符串拼接（不是模板引擎）：
   │                             #   请求 + TaskPlanningContext 的 Agent 描述段
   │                             #   （与下面的 Repair 共用同一个 build_agent_prompt_section）+ 约束
   ▼
PlannerProvider.complete(prompt) -> str   # 极简 Protocol，只有一个方法，
   │                                       # 故意不是完整的 LLMProvider/LLMRequest 契约
   ▼
PlannerResponseParser.parse(raw)  # json.loads，格式不对/字段缺失直接抛，不做宽容降级
   │
   ▼
PlannerOutput(steps: list[PlannedStep])
   │
   ▼
TaskPlan（ClaudePlanner 自己转换，不做校验——校验仍然是 PlanValidator 的职责）
```

`PlanningContext`（`planning_context.py`，`available_agents: list[str]` + `constraints`）是更早、更简单的旧形状；`TaskPlanningContext`（`task_planning_context.py`）是 Task-Scoped Agent 架构下的替代品：`available_agents: list[TaskAgentInfo]`（不是裸 id）+ `task_id` + 可选的项目 `ContextSnapshot`。由 `TaskPlanningContextFactory.create(task_id)` 构建，联结 `TaskAgentRegistry.list_agents(task_id)` 和 `AgentTemplateRepository`；如果某个 `TaskAgent` 的 `template_id` 解析不到对应模板，视为数据损坏直接抛 `AgentTemplateNotFoundError`，不会静默降级。

**当前状态**：`ClaudePlanner` 已经完整实现并有单测（`tests/planning/test_claude_planner.py`）和用 `FakeProvider` 跑通的集成测试（`test_claude_planner_integration.py`），但 `ManagerAgent.__init__` 里默认仍然是 `self._planner = planner or RuleBasedPlanner()`——**还没有任何生产代码路径把 `ClaudePlanner` 接成默认 Planner**，要用必须显式注入。

**计划自修复循环**（`PlanRepairLoop.run()`，`src/planning/plan_repair_loop.py`）：`Planner.create_plan()` 生成计划 → `PlanValidator` 校验；不通过就进入最多 `max_attempts`（默认 3）次的修复循环——`RepairDecisionService.decide(validation)` 先判断值不值得修（`validation.repairable`），值得的话 `RepairRequestBuilder` 组一个 `PlanRepairRequest`（`source=VALIDATION`），交给 `RepairPlanner.repair()`（复用同一个 `build_agent_prompt_section` + `PlannerResponseParser`，`RepairPromptBuilder` 会按来源写不同的开场白）重新生成计划，再校验一轮；超过 `max_attempts` 或校验器说不可修，抛 `PlanRepairLimitExceeded`。

有两条不同的入口能触发修复：`RepairRequestBuilder`（计划**校验时**发现的问题）和 `FailureRepairRequestBuilder`（`failure_repair_request_builder.py`，把一次**执行期**的 `ExecutionFailure` 转成 `source=EXECUTION_FAILURE` 的修复请求）——后者是下一节"执行恢复"里 `RecoveryExecutor` 触发 `REPAIR_PLAN` 时的入口。`RuntimePlanRepairService`（`runtime_plan_repair_service.py`）是刻意做薄的适配层：让 Recovery 这一层完全不需要 import `RepairPlanner`（Planning 层的概念），不做 `TaskPlan` 转换、不改状态、不重新校验。整个修复循环里，`context` 只在最外层解析一次，之后每次重试都原样复用，不会中途重新解析——保证 Claude 在多次重试之间看到的 Agent 边界不会漂移。

## 执行恢复与重规划（5E-5，尚未接入 CLI）

如果调度中某个 `TaskStep` 失败了，不该总是"整个计划就地失败"——`TEMPORARY_ERROR` 可能重试就好，`PLAN_ERROR` 需要重新规划，`BLOCKED`（比如权限不足）需要人来决定，真正的 `FATAL` 才应该放弃。这一整条"失败之后该怎么办"的决策链已经实现并有集成测试覆盖，但**还没有接入任何 CLI 命令**——目前只能被其它代码/测试直接调用。

```text
TaskStep 执行抛出异常
   │
   ▼
FailureClassifier.classify(exc, step_id)      # src/failure_classifier.py
   │  固定的 Exception → FailureCategory 映射：
   │  TimeoutError/ConnectionError → TEMPORARY_ERROR
   │  PermissionError → BLOCKED
   │  其它一律 → FATAL（未知异常默认最保守，不是默认宽容）
   ▼
ExecutionFailure(category, message, step_id)
   │
   ▼
RecoveryPlanner.decide(failure)                # src/recovery_planner.py
   │  TEMPORARY_ERROR → RETRY
   │  PLAN_ERROR      → REPAIR_PLAN
   │  BLOCKED         → REQUEST_APPROVAL
   │  FATAL           → ABORT
   │  （出现没覆盖到的分类会直接抛 ValueError，而不是静默兜底——
   │   把"分类没覆盖全"当成代码 bug，不是运行时可以吞掉的情况）
   ▼
RecoveryOrchestrator.plan(PlanExecutionResult)  # 给每个失败的 step 配一个 RecoveryAction，
   │                                             # 纯决策，不执行
   ▼
RecoveryPlan(list[RecoveryStepAction])
   │
   ▼
RecoveryExecutor.execute(plan, RecoveryExecutionContext)
   ├── RETRY            → 真的调 RetryManager.execute() 重跑这一步
   ├── REPAIR_PLAN       → FailureRepairRequestBuilder + RuntimePlanRepairService（见上一节）
   ├── REQUEST_APPROVAL  → RuntimeApprovalService.create()，执行停在这里等人
   └── ABORT             → 目前直接跳过，终止逻辑还没接（已知缺口）
```

- **运行时审批闸门**（`src/runtime_approval_*.py`）：`RuntimeApprovalRequest`（`approval_id`/`task_id`/`plan_id`/`failure`/`status="pending"`）持久化在 `tasks/<task-id>/runtime_approval.json`——**和上一节 `plan` 审批用的 `approval.json` 是两个不同的文件**，刻意分开避免互相覆盖。`RuntimeApprovalService.create()/approve()/reject()` 只接受从 `pending` 出发的状态转换，否则抛 `RuntimeApprovalStateError`，防止悄悄覆盖人已经做过的决定。**它和 README 前面"人工审核：`ChangeSnapshot` 与 `review` 命令"是两套不同的闸门**：`review` 是 Run 级、事后的——一次 Run 已经成功跑完、改了文件，之后人来决定要不要认；这个新的运行时审批是 Task/计划执行**过程中**的——某一步失败并且被分类成 `BLOCKED`，执行当场卡住，后续步骤在人做出决定前完全不会被派发。
- **检查点与恢复继续**：`ExecutionCheckpoint`（`src/execution_checkpoint.py`：`task_id`/`plan_id`/`completed_step_ids`/`step_results`/`blocked_step_id`）由 `ExecutionCheckpointRepository` 存到 `tasks/<task-id>/checkpoint.json`。**已知缺口**：目前没有 `CheckpointWriter`——没有任何生产代码会在一次 `PlanExecutionResult` 产生后自动把它写成 `ExecutionCheckpoint`；集成测试（`test_recovery_approval_flow.py`）是手工构造检查点来验证恢复路径本身是真实可用的。人工批准后，`RecoveryContinuationService.resume_after_approval()`（`src/recovery_continuation_service.py`）确认 `RuntimeApprovalRequest.status == "approved"`（pending/rejected 都拒绝并抛 `RecoveryContinuationError`），交给 `TaskPlanResumeService.resume()`（`src/planning/task_plan_resume_service.py`）——它加载检查点、用 `ResumePlanBuilder.build(plan, checkpoint)` 剔除已完成的 step **并且改写剩余 step 的 `depends_on`，去掉指向已完成 step 的引用**（否则 `TaskDependencyResolver` 会把一次正常的"接着跑"误判成依赖悬空/成环），再把这份缩小后的计划交给**完全不知道自己在做"恢复"**的、原封不动的 `TaskScheduler` 去跑。
- **Task 完成收尾**：`TaskCompletionService.complete_if_successful(task_id, result: PlanExecutionResult)`（`src/planning/task_completion_service.py`）——只有 `result.succeeded` 才会把 Task 状态从 `in_progress` 推进到 `completed`（已经是 `completed` 时是幂等 no-op；状态不是 `in_progress` 时抛 `TaskCompletionStateError`）。这是目前 CLI 里唯一真正在用的收尾入口——`approve-plan` 执行完计划后会调它，成功就顺带触发上一节的 `TaskAgentCleanupService.cleanup()`。

**测试**：`tests/integration/test_recovery_approval_flow.py`（真实 `PermissionError` → `BLOCKED` → `RecoveryOrchestrator`/`RecoveryExecutor`/`RuntimeApprovalService` 全链路，验证 pending/rejected 时恢复会被拒绝、跨 Task 审批互不干扰、同一个 `RecoveryPlan` 里混合 RETRY/REPAIR_PLAN/REQUEST_APPROVAL 互不干扰，全部走真实 `TaskScheduler`）、`tests/test_recovery_*.py`、`tests/test_retry_manager.py`、`tests/test_failure_classifier.py`、`tests/test_execution_checkpoint*.py`、`tests/test_runtime_approval_*.py`。

## 一个独立的、更早期的原型：容器化 Agent Runtime

`runtime/`（`Dockerfile` + `agent.sh`）和 `scripts/`（`run-agent.sh`/`stop-agent.sh`/`status-agent.sh`/`logs-agent.sh`/`remove-agent.sh`）是这个项目更早期的一版思路留下的：把每个 Agent 跑成一个独立的 Docker 容器，通过 shell 脚本管理容器生命周期。目前 `agent.sh` 里的"执行任务"部分只是 `sleep 5` 加写一个占位输出文件，**还没有和上面 `src/` 里的 Task/Run/Agent 主链路打通**。这部分可以理解为容器化隔离运行时的技术验证草稿，如果要用起来还需要单独规划。

## 已知限制 / 待办

- 纯文件系统持久化（JSON + Markdown），没有数据库，也没有并发写保护——多进程同时操作同一个 Task/Run 会有竞态风险。
- `write_file` 只支持整篇创建/覆盖，没有 append 能力；局部编辑现在由 `patch_file` 覆盖（唯一匹配的文本替换），但 `patch_file` 只能替换单个精确匹配的文本块，不支持传统的多段 unified diff 一次应用多处修改。
- `run_test` 只能跑 `src/config/test_policy.json` 里预先注册好的命令（目前是整个 `pytest -q` 套件和 `compileall`），不能只跑某一个测试文件/测试函数——Agent 想验证一处小改动，也得等全量测试跑完（当前项目规模下约 3~4 秒，可接受，但会随测试量增长变慢）。
- `JsonlRunEventSink` 每次 `emit()` 都单独 open/append/close 文件，实现简单、异常安全，但工具调用非常频繁时会有额外的文件系统开销——目前项目规模下可以接受，量级上去后可以换成常驻文件句柄。
- 目前没有正式的"创建 Run"命令/流程——本 README 里所有 `run-NNN` 都是手动创建 `run.json`/`input.md` 再把 `task.json.current_run_id` 指过去的；因此也没有用到状态机里理论上存在的 `pending` 状态，Run 一创建出来就是 `in_progress`。
- `resume`/`review`/`get_run()`/`inspect`（`RunQueryService` 自己也重新实现了一遍同样的查找）都是用扫描全部 Task 的 `runs/` 目录来按 `run_id` 反查所属 Task，Run 数量大了以后是线性开销；`run_id` 本身只在单个 Task 内保证唯一，跨 Task 撞号时会静默解析到（按 Task 目录字母序）第一个匹配的——手工测试 `review`/`inspect` 时都实际踩到过这个问题，不是 5C-4/5C-5 新引入的，`resume` 早就有同样的行为。状态机里 `interrupted → failed`（放弃转重试为放弃）还没有对应的 CLI 命令，需要手动改 `run.json`。
- `RunEvent.timestamp` 目前恒为 `None`：真实 `events.jsonl` 从来没有 `timestamp` 字段（`llm_executor.py` 用 `round` 排序，不是墙钟时间），`TimelineBuilder` 也刻意不做排序——完全依赖 `events.jsonl` 本身的 append 顺序。如果以后需要跨 Run 按时间对齐事件（而不只是看单个 Run 内部的先后顺序），需要先让 `llm_executor.py` 真正写入时间戳。
- `review` 命令目前没有 Reviewer Agent：`ReviewReport.summary`/`risks` 恒为 `None`/`[]`，diff 内容也从不生成（`ChangeSnapshot.diff_path` 目前恒为 `null`，因为没有代码会写 `diff.patch`）——审核时只能看 `changed_files`/`mutation_count`/`test_results`，看不到具体改了什么行。approve/reject 也只是把 `run.json.status` 改成 `approved`/`rejected`，不会自动 `git commit`。
- 容器化 Agent Runtime（`runtime/` + `scripts/`）与主执行链路是两套独立的东西，尚未整合。
- 只支持 Anthropic 一家 provider；`LLMProvider` 协议本身是 provider 无关的，理论上可以扩展。
- **History Compression（见上方专门章节）只压缩对话历史，不压缩每轮都会重发的静态上下文快照**——如果 Run 报 `Maximum total token limit exceeded` 但 `events.jsonl` 里 `compaction_report` 的 `removed_count` 一直是 0，问题大概率在 `RunContextBuilder` 选出来的 `initial_message` 太大，不在压缩算法本身；两次真实 smoke test 都是这个原因触发的失败，不是压缩逻辑的 bug。
- `RuleBasedContextSizeEstimator`（见"Static Context Optimization"一节）只估算 `ContextSnapshot` 的元数据（路径/理由/项目目录树），不读文件内容，所以静态上下文的裁剪是"按文件数量丢文件"，不是按真实 token 数精确截断到预算线以内。
- `ClaudePlanner`（见"Claude 结构化规划"一节）已经实现、测试齐全，但 `ManagerAgent` 默认仍然是 `RuleBasedPlanner`——没有任何生产路径会自动用上 Claude 规划，必须调用方显式注入。
- 执行恢复层（见"执行恢复与重规划"一节）**完全没有接入 CLI**，只能通过直接调用 `RecoveryOrchestrator`/`RecoveryExecutor` 使用；`RecoveryAction.ABORT` 目前是静默跳过，没有真正的终止逻辑；也没有 `CheckpointWriter`——没有任何生产代码会在计划执行后自动生成 `ExecutionCheckpoint`，恢复路径本身可用，但触发恢复所需的检查点目前只能手工构造。
- Task-Scoped Agent 架构里的 `AgentTemplateRepository`（`src/agents/agent_template_repository.py`）目前是纯内存实现，没有持久化到磁盘，进程重启就丢。
- 运行时审批（`runtime_approval.json`）和计划审批（`approval.json`）是两个独立文件、两套独立状态机，都还没有对应的 CLI 命令去查看/审批"运行时审批"——只有计划审批（`plans`/`approve-plan`/`reject-plan`）接了 CLI。
