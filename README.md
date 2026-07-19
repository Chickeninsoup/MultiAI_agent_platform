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

Agent 在 `llm` 模式下现在拥有 4 个只读工具：

| 工具 | 作用 |
|---|---|
| `list_files` | 列出仓库内某个目录下的文件/子目录 |
| `read_file` | 读取仓库内某个文本文件，支持指定行号范围 |
| `git_status` | 查看当前分支和工作区状态（`git status --short --branch`） |
| `git_diff` | 查看未暂存或已暂存的改动（`git diff`） |

**关键设计点**：

- 所有工具都通过 `PathGuard`（`src/services/tools/path_guard.py`）做路径边界检查——请求路径必须解析到仓库根目录以内，拒绝 `../` 逃逸和软链接逃逸。
- 每个 Agent 有自己独立的 `tool-policy.json`（`default: allow/deny` + 每个工具的 `enabled`/`max_output_chars`），决定它能用哪些工具、单次工具输出最多多少字符。
- `ToolExecutor`（`src/services/tools/tool_executor.py`）是统一调度层：按名字找 handler、按策略校验是否启用、捕获异常统一转成失败态 `ToolResult`，不会让一次工具调用失败直接炸掉整个 Run。
- `LLMRunExecutor`（`src/llm_executor.py`）实现真正的**多轮工具调用循环**：请求模型 → 如果模型要调用工具就执行 → 把工具结果作为下一轮消息喂回去 → 再次请求，直到模型给出最终文本回答。有 `max_tool_rounds`（默认 8 轮）和 `max_total_tokens`（默认 100000）两道保险，防止死循环或失控的开销。
- `LLMAgentRunExecutor` 是适配层，把 Task/Run/Agent 那一套 `RunExecutionContext` 翻译成 `LLMRequest`，按当前 Run 的 Agent 现建对应的 `ToolExecutor`，再把最终结果翻译回 `RunExecutionResult`（Markdown 格式的 output/summary）。

这条链路已经用真实 API 端到端验证过（`tasks/task-20260713-001` 的 run-007）：模型依次真实调用了 `list_files`/`read_file`/`git_status`/`git_diff`，返回内容和仓库实际状态完全对得上。

**已知限制**：output.md/summary.md 里记录的 token 用量目前只是**最后一轮**的用量，不是整个多轮会话的累计值（`LLMRunExecutor` 内部有累计但还没对外暴露）。

## 架构分层

```
src/
├── models.py              # 领域模型：TaskDefinition / RunDefinition / AgentDefinition（纯 dataclass，from_dict/to_dict 做校验）
├── repositories.py        # 持久化层：读写 JSON/Markdown 文件（没有数据库，任务/运行数据就是 tasks/ 目录下的文件树）
├── execution.py           # RunExecutor 协议（Protocol）：execute(context) -> RunExecutionResult
├── context_builder.py     # 把 Task+Run+Agent 拼成一份带项目快照的 RunExecutionContext
├── run_service.py         # 编排一次 Run 的完整生命周期：加载→校验→执行→落盘→标记完成
├── executor_factory.py    # 按 EXECUTION_MODE 组装对应的 RunExecutor（simulated / llm）
├── simulated_executor.py  # 确定性占位执行器
├── llm_executor.py        # LLMRunExecutor（原始多轮工具循环）+ LLMAgentRunExecutor（接入 Task/Run 的适配层）
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
    ├── run.json           # 状态、时间戳、（可选）自定义 context_files
    ├── input.md            # 本轮的具体指令
    ├── output.md           # 模型的完整回答（含 token 用量等元信息）
    └── summary.md          # 简短摘要
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

## 测试

```bash
.venv/bin/python -m pytest tests/ -v
```

当前 53 个测试，覆盖：工具的路径防护、四个具体工具的正确性、`ToolExecutor` 的调度/策略/异常兜底逻辑、`ToolPolicy` 的 JSON 解析校验、`AnthropicProvider` 的请求构造与响应解析（mock 掉真实网络请求）、`LLMRunExecutor` 的多轮循环行为（工具失败传播、轮次超限）。

> 注意：`pytest` 需要在装了 `anthropic`/`python-dotenv` 的同一个环境（`.venv`）里跑，否则涉及 Anthropic Provider 的测试会因为 `ModuleNotFoundError: No module named 'anthropic'` 而无法 collect。

## 一个独立的、更早期的原型：容器化 Agent Runtime

`runtime/`（`Dockerfile` + `agent.sh`）和 `scripts/`（`run-agent.sh`/`stop-agent.sh`/`status-agent.sh`/`logs-agent.sh`/`remove-agent.sh`）是这个项目更早期的一版思路留下的：把每个 Agent 跑成一个独立的 Docker 容器，通过 shell 脚本管理容器生命周期。目前 `agent.sh` 里的"执行任务"部分只是 `sleep 5` 加写一个占位输出文件，**还没有和上面 `src/` 里的 Task/Run/Agent 主链路打通**。这部分可以理解为容器化隔离运行时的技术验证草稿，如果要用起来还需要单独规划。

## 已知限制 / 待办

- 纯文件系统持久化（JSON + Markdown），没有数据库，也没有并发写保护——多进程同时操作同一个 Task/Run 会有竞态风险。
- 工具目前全部只读（`list_files`/`read_file`/`git_status`/`git_diff`），还没有写文件/编辑文件类的工具和对应的 handler。
- 多轮工具调用会话的 token 用量统计只反映最后一轮，非累计。
- 容器化 Agent Runtime（`runtime/` + `scripts/`）与主执行链路是两套独立的东西，尚未整合。
- 只支持 Anthropic 一家 provider；`LLMProvider` 协议本身是 provider 无关的，理论上可以扩展。
