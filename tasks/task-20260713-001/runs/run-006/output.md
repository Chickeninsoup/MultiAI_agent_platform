# Run Output

- Task ID: `task-20260713-001`
- Run ID: `run-006`
- Agent ID: `agent-general`
- Provider: `anthropic`
- Model: `claude-sonnet-5`
- Input tokens: `21691`
- Output tokens: `2228`

## Agent Response

# AI Agent Platform 架构审查

## 1. Task / Run / Agent 职责划分

- 观察事实：`models.py` 中 `TaskDefinition`、`RunDefinition`、`AgentDefinition` 三者字段互不重叠，`RunDefinition.agent_id` 与 `TaskDefinition.assigned_agents` 建立了引用关系而非嵌入关系，职责边界清晰。
- 观察事实：`RunService.execute` 中通过 `task.is_agent_assigned(run.agent_id)` 和 `agent.status != "ready"` 分别校验任务授权与 Agent 可用性，说明 Task 状态与 Agent 状态确实是分离校验的，符合背景要求“Task 状态与 Run 状态分离”。
- 风险（推断）：`RunDefinition` 没有独立的 `RunStatus` 枚举校验，`is_completed()` 仅做字符串比较，状态机（pending/running/completed/failed）尚未显式建模，未来多 Run 并发或失败重试语义不明确。

## 2. Repository / RunService / Executor / LLM Provider 分层

- 观察事实：`repositories.py` 的 `JsonRepository`/`TextRepository` 与 `TaskRepository`/`RunRepository`/`AgentRepository` 形成了清晰的“通用存取 + 领域仓储”两层，职责单一，`RunService` 不直接操作文件路径而是调用仓储方法，分层合理。
- 观察事实：`RunExecutor` 是 `execution.py` 中定义的 `Protocol`，`LLMRunExecutor`（`llm_executor.py`）与 `SimulatedRunExecutor` 都实现该协议，`executor_factory.create_run_executor` 按 `Settings.execution_mode` 做工厂选择，`RunService` 只依赖抽象接口，符合依赖倒置。
- 风险（推断）：`LLMRunExecutor._build_request` 中混合了“系统提示词拼装”“任务背景注入”“工具策略序列化”等多项职责，属于 Prompt 构建逻辑，理论上应下沉到 `RunContextBuilder` 或独立的 PromptAssembler，目前该类同时承担“调用 LLM”和“组装 Prompt”两种职责，边界略有模糊。

## 3. RunContextBuilder 优势与风险

- 优势（观察事实）：`RunContextBuilder.build` 严格通过仓储读取 `run_input`、`agent_system_prompt`、`tool_policy`、`task_background`，并用 `_validate_context_path` 对 `context_files` 做路径穿越校验（禁止 `..`、绝对路径、排除目录），具备较强的安全边界。
- 优势（观察事实）：`_build_project_snapshot` 有明确的字符预算控制（`max_file_characters`、`max_snapshot_characters`），并对截断做了显式标注，保证上下文是确定性、可预测的静态快照。
- 风险（推断）：该 Snapshot 是一次性静态构建，`RunExecutionContext` 一旦生成即不可变（`frozen=True`），说明当前架构只支持“一次性单轮上下文注入”，不支持 Agent 在执行过程中动态请求新文件或工具结果后再更新上下文。

## 4. 距离真正多轮 Agent 工具执行还缺什么

- 事实依据：`llm/base.py` 的 `LLMProvider.generate` 只接受 `LLMRequest` 并返回单个 `LLMResponse`，`LLMRequest`/`LLMMessage`（`llm/types.py`）没有 `tool_use`/`tool_result` 相关字段，说明当前完全没有工具调用（function calling）协议。
- 事实依据：Agent 的 `tool-policy.json`（如 `agents/agent-general/tool-policy.json`）目前仅作为文本被 `RunContextBuilder.format_tool_policy` 序列化后塞进 Prompt，并未在代码层面被任何执行器解析或强制执行，工具策略是“建议性文本”而非可执行约束。
- 事实依据：`RunService.execute` 是单次调用 `self._executor.execute(context)` 后直接写 `output`/`summary` 并将 Run 置为 `completed`，没有循环（loop）结构，缺少“LLM 请求工具 → 平台执行工具 → 结果回填 → 再次请求模型”的多轮状态机。

## 5. 接下来三个最重要的实现优先级（推荐，非既定事实）

1. 在 `execution.py` 与 `llm/types.py` 中引入工具调用协议（`tool_use`/`tool_result` 消息类型），并让 `LLMRunExecutor` 支持多轮 `while` 循环，替代目前的单次 `generate` 调用。
2. 将 `tool-policy.json` 从纯文本提示升级为真实的执行时白名单校验模块，在工具被调用前由平台代码（而非模型自觉）强制检查 `allowed_tools`/`filesystem_policy`。
3. 为 `RunDefinition` 引入显式状态机（如 `pending/running/completed/failed`）并在 `RunService` 中区分“执行失败”与“执行完成”，为后续多轮工具执行的中断恢复打基础。
