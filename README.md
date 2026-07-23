# Claude Agent Platform

一个用于管理「任务（Task）→ 运行（Run）→ 智能体（Agent）」工作流的私有 Python 平台。Agent 通过 Anthropic Claude API 执行任务，并且现在**可以真实调用工具**（读文件、列目录、查 git 状态/diff）来完成任务，而不只是根据静态快照臆测答案。

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

Agent 在 `llm` 模式下有 4 个只读工具，外加一个默认关闭、只对 `agent-coder` 开放的写文件工具：

| 工具 | 作用 |
|---|---|
| `list_files` | 列出仓库内某个目录下的文件/子目录 |
| `read_file` | 读取仓库内某个文本文件，支持指定行号范围 |
| `git_status` | 查看当前分支和工作区状态（`git status --short --branch`） |
| `git_diff` | 查看未暂存或已暂存的改动（`git diff`） |
| `write_file` | 在仓库内创建（`mode: create`）或整篇覆盖（`mode: overwrite`）一个 UTF-8 文本文件；只在 `agents/agent-coder/tool-policy.json` 里 `enabled: true`，`agent-general` 保持关闭 |

**关键设计点**：

- 所有工具都通过 `PathGuard`（`src/services/tools/path_guard.py`）做路径边界检查——请求路径必须解析到仓库根目录以内，拒绝 `../` 逃逸和软链接逃逸；`write_file` 额外用 `resolve_repository_write_path()` 处理目标文件尚不存在的情况（不自动创建父目录，父目录本身的软链接逃逸也会被拒绝）。
- `write_file` 不会自动覆盖：`create` 遇到已存在的文件直接报错，`overwrite` 遇到不存在的文件也直接报错，两种模式语义互不兼容；写入内容有按字节数的上限（`max_write_bytes`），`.git`/`.env`/私钥/虚拟环境等敏感路径永远拒绝；实际落盘用 `mkstemp` + `fsync` + `os.replace` 做原子替换，避免进程中途崩溃留下半个文件。
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
- `tool_result`：平台**实际执行**的结果——成功/失败、`error_code`、`output_chars`、`truncated`、`duration_ms`（`ToolExecutor.execute()` 统一计时，成功/失败路径都有）。`tool_call`/`tool_result` 是两条独立事件，不合并成一条。
- `run_limit_exceeded`：触发 `max_total_tokens`/`max_tool_rounds` 限制时记一条（`limit`/`configured_limit`/`actual_value`/`round`），紧接着会抛出 `LLMRunLimitError`。
- `run_completed`：Run 正常结束（`end_turn`，无更多工具调用）时记一条，带累计的 `llm_rounds`/`tool_rounds`/`tool_calls`/`total_input_tokens`/`total_output_tokens`。
- `run_failed`：`LLMRunExecutor.execute()` 内部只要抛出任何异常（包括 `run_limit_exceeded` 之后的 `LLMRunLimitError`），外层都会补记一条 `run_failed`（`error_type`/`message`），然后原样把异常继续往上抛——所以触发限制的 Run 会同时看到 `run_limit_exceeded` 和 `run_failed` 两条。
- **默认不记录工具的完整输出**（可能是完整文件内容或完整 git diff，体积大、可能包含源码/敏感信息、和 output.md 里的内容重复）。只有把 `.env` 里的 `DEBUG_LOG_FULL_OUTPUT` 设为 `true` 时，`tool_result` 事件才会额外带上完整的 `output` 字段；`tool_call` 的参数（`input`）本身体积通常很小，默认就会记。

`error_code` 目前的取值集合（`src/services/tools/tool_executor.py`/`path_guard.py`/`git_command.py`/`read_file_tool.py`）：`UNKNOWN_TOOL`、`TOOL_DISABLED`、`INVALID_TOOL_INPUT`、`PATH_OUTSIDE_REPOSITORY`、`PATH_NOT_FOUND`、`GIT_COMMAND_FAILED`、`TOOL_EXECUTION_FAILED`（兜底）——看到失败的 Run，可以直接从 `error_code` 判断问题出在模型选择、policy 拒绝、输入格式、路径安全、Git 环境还是工具实现本身。

### File mutation 审计

写入类工具（目前是 `write_file`）成功执行后，`events.jsonl` 里除了通用的 `tool_result`，还会额外多记一条 `file_mutation`：

```jsonl
{"type": "file_mutation", "round": 1, "tool_call_id": "toolu_...", "operation": "create", "path": "src/example.py", "before_sha256": null, "after_sha256": "9f86d0...", "bytes_written": 13}
```

- `operation`：`create` 或 `overwrite`。
- `before_sha256`：写入前文件内容的 sha256；`create` 场景下没有旧文件，恒为 `null`。
- `after_sha256`：写入后文件内容的 sha256。
- `bytes_written`：写入的 UTF-8 字节数（不是字符数）。

`LLMRunExecutor`（`src/llm_executor.py`）判断是否要发这条事件，看的是 `ToolResult.metadata` 里有没有 `after_sha256` 这个 key，不是硬编码判断 `tool_name == "write_file"`——以后任何新的写入类工具（比如规划中的 `apply_patch`）只要在 `metadata` 里填上同样几个字段，不用改 `llm_executor.py` 就能自动获得审计事件。

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
in_progress → completed                （正常结束）
in_progress → interrupted              （可重试的失败：限流/Provider 抖动/进程崩溃）
in_progress → failed                   （不建议重试的失败：配置错误/内部 bug）
```

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

## 架构分层

```
src/
├── models.py              # 领域模型：TaskDefinition / RunDefinition / AgentDefinition / RunExecutionContext / RunExecutionResult（纯 dataclass，from_dict/to_dict 做校验）
├── repositories.py        # 持久化层：读写 JSON/Markdown/JSONL 文件（没有数据库，任务/运行数据就是 tasks/ 目录下的文件树）
├── execution.py           # RunExecutor 协议（Protocol）：execute(context) -> RunExecutionResult
├── context_builder.py     # 把 Task+Run+Agent 拼成一份带项目快照的 RunExecutionContext
├── run_service.py         # 编排一次 Run 的完整生命周期：加载→校验→执行→落盘→标记完成/interrupted/failed；execute()/resume() 都返回 RunServiceResult，失败时抛 RunExecutionFailedError
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
└── services/tools/         # 工具调用的服务层
    ├── tool_executor.py     # 统一调度
    ├── tool_policy.py       # 策略加载与校验
    ├── path_guard.py        # 仓库路径边界防护
    ├── git_command.py       # git 子进程调用的公共封装
    └── handlers/             # 四个具体工具的实现
```

配置和 Agent 定义：

```
agents/<agent-id>/
├── agent.json           # 名称、角色、默认模型、资源限制、能力标签
├── system-prompt.md     # 该 Agent 专属的 system prompt
└── tool-policy.json      # 该 Agent 的工具权限策略

tasks/<task-id>/
├── task.json             # 状态、当前 Run、Run 计数、完成标准
├── background.md         # 跨 Run 共享的累积背景
└── runs/run-NNN/
    ├── run.json           # 状态（in_progress/completed/interrupted/failed）、时间戳、（可选）retry_of/error_category/error_message/retryable/context_files
    ├── input.md            # 本轮的具体指令
    ├── output.md           # 模型的完整回答（含累计 token 用量等元信息）
    ├── summary.md          # 简短摘要（含累计 token/轮次/工具调用次数）
    └── events.jsonl        # 每轮 LLM 调用/工具调用的结构化审计记录，实时追加写入（llm 模式才有）
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

## 测试

```bash
.venv/bin/python -m pytest tests/ -v
```

当前 81 个测试，覆盖：工具的路径防护、四个具体工具的正确性、`ToolExecutor` 的调度/策略/异常兜底逻辑（含 `duration_ms` 计时）、`ToolPolicy` 的 JSON 解析校验、`AnthropicProvider` 的请求构造与响应解析（mock 掉真实网络请求）、`RunEventSink` 实现（`tests/test_run_events.py`：内存/JSONL/丢弃三种 sink，JSONL 的 unicode 与 truncate 行为）、`LLMRunExecutor` 的多轮循环行为（工具失败传播、轮次超限、累计 usage/events、中途异常仍保留已发生事件、debug 开关）、`LLMAgentRunExecutor` 适配层（mock `LLMProvider`/`AgentRepository`，真实 `ToolExecutor`/`RunRepository`，含 events.jsonl 与 debug 模式，见 `tests/test_llm_agent_run_executor.py`）、错误分类（`tests/test_run_errors.py`：6 类 `RunErrorCategory` 与默认可重试性）、`RunService`（`tests/test_run_service.py`：成功路径的 `RunServiceResult`、simulated 风格的空 usage 字段、`LIMIT_EXCEEDED`→`interrupted` 与未分类错误→`failed` 两种失败路径、`resume()` 的崩溃检测/新建 Run/`retry_of` 链接/拒绝重跑非法状态）。

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

## 一个独立的、更早期的原型：容器化 Agent Runtime

`runtime/`（`Dockerfile` + `agent.sh`）和 `scripts/`（`run-agent.sh`/`stop-agent.sh`/`status-agent.sh`/`logs-agent.sh`/`remove-agent.sh`）是这个项目更早期的一版思路留下的：把每个 Agent 跑成一个独立的 Docker 容器，通过 shell 脚本管理容器生命周期。目前 `agent.sh` 里的"执行任务"部分只是 `sleep 5` 加写一个占位输出文件，**还没有和上面 `src/` 里的 Task/Run/Agent 主链路打通**。这部分可以理解为容器化隔离运行时的技术验证草稿，如果要用起来还需要单独规划。

## 已知限制 / 待办

- 纯文件系统持久化（JSON + Markdown），没有数据库，也没有并发写保护——多进程同时操作同一个 Task/Run 会有竞态风险。
- `write_file` 只支持整篇创建/覆盖，没有 append 或按 diff 局部编辑的能力——改一个大文件的一小部分也得把全文重新传一遍。局部编辑（`apply_patch`/`edit_file`）还没做。
- `JsonlRunEventSink` 每次 `emit()` 都单独 open/append/close 文件，实现简单、异常安全，但工具调用非常频繁时会有额外的文件系统开销——目前项目规模下可以接受，量级上去后可以换成常驻文件句柄。
- 目前没有正式的"创建 Run"命令/流程——本 README 里所有 `run-NNN` 都是手动创建 `run.json`/`input.md` 再把 `task.json.current_run_id` 指过去的；因此也没有用到状态机里理论上存在的 `pending` 状态，Run 一创建出来就是 `in_progress`。
- `resume` 用扫描全部 Task 的 `runs/` 目录来按 `run_id` 反查所属 Task，Run 数量大了以后是线性开销；状态机里 `interrupted → failed`（放弃重试）还没有对应的 CLI 命令，需要手动改 `run.json`。
- 容器化 Agent Runtime（`runtime/` + `scripts/`）与主执行链路是两套独立的东西，尚未整合。
- 只支持 Anthropic 一家 provider；`LLMProvider` 协议本身是 provider 无关的，理论上可以扩展。
