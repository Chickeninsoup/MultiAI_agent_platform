# Claude Agent Platform

一个用于管理「任务（Task）→ 计划（Plan）→ 运行（Run）→ 智能体（Agent）」工作流的私有 Python 平台。Agent 通过 Anthropic Claude API 执行任务，并且**可以真实调用工具**（读文件、列目录、查 git 状态/diff，特定 Agent 还能创建/修改文件、跑受限的测试命令）来完成任务，而不只是根据静态快照臆测答案。高风险的工具调用、Run 产生的文件改动、计划执行中的阻塞性失败，都分别有独立的人工审批闸门把关。

> 早期原型阶段，个人项目，正在快速迭代。本 README 分两部分：**第一部分**是搭建和使用这个多 Agent 平台的实操指南；**第二部分**是当前工程进度——已完成什么、正在做什么、接下来打算做什么。

---

# 第一部分：搭建与使用指南

## 1. 核心概念

平台围绕四个实体组织工作：

- **Task（任务）**：一个长期存在的工作项，比如"审查项目架构"。一个 Task 可以包含多个 Run，Run 之间共享同一份 `background.md`（任务背景，会随着每个 Run 完成后累积更新）。
- **Agent（智能体）**：一个可复用的执行角色配置——system prompt、默认模型、资源限制（token/内存/超时）、工具权限策略（`tool-policy.json`）。Agent 本身不绑定某个 Task，可以被多个 Task 先后复用（`agents/agent-general`、`agents/agent-coder`）。
- **Run（运行）**：Task 下的一次具体执行。每个 Run 有自己的输入（`input.md`）、输出（`output.md`）和摘要（`summary.md`），由某一个 Agent 执行，过程中可能发起多轮工具调用，也可能因为触发审批闸门而暂停。
- **TaskPlan（计划）**：一个 Task 可以先被 `ManagerAgent` 拆成一份带依赖关系的多步计划（每步指定由哪个 Agent 执行），经人工批准后再按依赖顺序调度执行——这是"一次 Run 执行一个工具调用循环"之上更高的一层编排，用于拆解复杂、需要多个 Agent 协作的任务。

## 2. 两种执行模式

由 `.env` 里的 `EXECUTION_MODE` 控制：

| 模式 | 说明 |
|---|---|
| `simulated` | 不调用任何模型，`SimulatedRunExecutor` 生成确定性的占位输出。用于跑通流程、写测试，不消耗 API 额度。 |
| `llm` | 真正调用 Anthropic API（`claude-sonnet-5`），Agent 可以使用真实工具执行多轮任务。 |

## 3. 安装与配置

```bash
# 1. 建虚拟环境、装依赖
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt

# 测试用的 pytest 目前不在 requirements.txt 里，需要单独装
.venv/bin/pip install pytest

# 2. 配置环境变量
cp .env.example .env
# 编辑 .env：至少要在 llm 模式下填 ANTHROPIC_API_KEY
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
| `DEBUG_LOG_FULL_OUTPUT` | `false` | `true` 时 `events.jsonl` 里的 `tool_result` 事件会额外带上工具的完整输出 |
| `TEST_POLICY_PATH` | `src/config/test_policy.json` | 相对 `project_root` 的路径，指向 `run_test` 的命令白名单文件 |

## 4. 命令总览

所有命令都是 `python -m src.main <command> ...`（下面省略 `.venv/bin/` 前缀）。按工作流分成五组。

### 4a. 基础：创建与执行

```bash
# 查看所有任务
python -m src.main list

# 创建一个新 Task 和它的第一个 Run（不会立即执行）
python -m src.main init-task <task-id> <agent-id> "<标题>" \
  --description "<描述，默认同标题>" \
  --input "<第一个 Run 的输入文本，默认同标题>"

# 执行某个任务当前的 Run
python -m src.main run <task-id>

# 恢复一个卡在 in_progress/interrupted 的 Run（创建新 Run 重试，不会复用同一个 run_id）
python -m src.main resume <run-id>
```

### 4b. 计划编排与审批（Plan 级，执行前）

把一个 Task 拆成多步、分配给不同 Agent 的计划，需要人工批准才会真正调度执行：

```bash
# 为一个 Task 生成一份待批准的 TaskPlan（只生成，不执行）
python -m src.main plan <task-id> "<用自然语言描述这次要做的工作>"

# 列出所有待审批的计划
python -m src.main plans

# 批准并立即执行（整份计划全部成功会触发 Task 完成收尾）
python -m src.main approve-plan <task-id>

# 拒绝，不执行
python -m src.main reject-plan <task-id>
```

### 4c. 变更审核（Run 级，执行后）

一次 Run 正常跑完、确实改动了文件（目前只有 `agent-coder` 会触发），会停在 `awaiting_review` 等人确认，而不是直接 `completed`：

```bash
# 查看一个 Run 改了什么文件、测试结果，并 approve/reject
python -m src.main review <run-id>
```

### 4d. 工具调用审批（ToolCall 级，执行中）

在"配置为需要审批"的工具真正被调用**之前**，Run 会原地暂停（状态变成 `waiting_for_approval`），等人做出决定后，用 `resume-after-approval` **继续同一个 Run**（不是创建新 Run）。闸门规则来自 `src/config/approval_policy.json`，默认是空规则列表（不配置就完全不触发，和这道闸门加入之前行为一致）。

**第一步：配置需要审批的工具**（`src/config/approval_policy.json`，`tool_name` 必须是真实注册的工具名）：

```json
{
  "rules": [
    {
      "tool_name": "write_file",
      "risk_level": "medium",
      "reason": "writes files inside the repository"
    }
  ]
}
```

`risk_level` 只能是 `low`/`medium`/`high`；配置里任何一条规则有误（未知工具名、风险等级拼错、重复的 `tool_name`、空的 `reason`）都会在 Run 执行前直接报错退出，不会静默退化成空规则。这份配置在一个 Run 的生命周期内是**固定**的：Run 启动时把当时生效的规则快照进 `tasks/<task-id>/runs/<run-id>/approval_rules.json`，之后哪怕 `approval_policy.json` 被改动甚至删掉，`resume-after-approval` 续跑这个 Run 时读的也是它自己的快照，不会读到变化后的新配置。

**第二步：启动一个会触发审批的 Run**（假设 `agent-coder` 被要求写一个文件）：

```bash
python -m src.main init-task task-20260101-001 agent-coder "write a file" --input "create greeting.txt with content 'hi'"
python -m src.main run task-20260101-001
```

输出里会看到 `Status: waiting_for_approval` 和一个 `Approval ID`，以及接下来每一步该敲哪条命令的提示。

**第三步：查询与决定**：

```bash
# 列出所有待处理的工具调用审批请求（可选 --run-id 过滤）
python -m src.main list-tool-approvals [--run-id <run-id>]

# 查看一条审批请求的安全元数据：工具名、风险等级、原因、输入预览（只含审查过的安全字段，
# 例如 write_file 只显示 path，不显示 content）、是否已决定、是否已应用/续跑
python -m src.main show-tool-approval <approval-id>

# 记录人工决定（只记录决定，不会执行工具/不会恢复 Run）
python -m src.main approve-tool-call <approval-id> [--explanation "..."]
python -m src.main reject-tool-call <approval-id> [--explanation "..."]
python -m src.main modify-tool-call <approval-id> --modified-input-file <path.json>
python -m src.main cancel-tool-call <approval-id> [--explanation "..."]
```

`modify-tool-call` 故意要求把替换后的工具参数放进一个 JSON 文件（`--modified-input-file`），而不是接受命令行里的原始 JSON 字符串，避免参数内容进 shell history。四种决定的最终效果（在下一步 `resume-after-approval` 时才真正生效）：`approve` 按原样执行工具；`modify` 用文件里的内容**完整替换**原输入后执行（不是和原输入合并）；`reject` 不执行这个工具，用一个固定的拒绝结果继续对话；`cancel` 整个 Run 终止（状态变成 `cancelled`），之后的工具调用和模型请求都不会再发生。

**第四步：显式续跑**（两个 ID 都必须给对——`approval-id` 是这次决定对应的那一条,不会因为你传错 ID 就偷偷续跑成另一条待处理的审批）：

```bash
python -m src.main resume-after-approval <run-id> <approval-id>
```

可能的结果：
- `Continued run ... Status: completed`（或 `awaiting_review`）——跑完了。
- `Continued run ... Status: cancelled`——对应 `cancel-tool-call`。
- `Continued run ... Status: waiting_for_approval` 并给出一个**新的** `Approval ID`——同一个 Run 里后面又有一个工具调用命中了规则，重复第三、四步处理这条新的审批即可（旧的那条审批如果重复执行 `resume-after-approval`，只会原样重放它当时的结果，不会碰到这条新的）。
- `Replayed an earlier completed continuation ...`——这条审批对应的续跑之前已经跑完过，这次只是重放当时记录下来的结果，没有重新执行任何工具或请求模型。
- 报错且提示"an incomplete continuation attempt"/"already owned elsewhere"——说明这个 Run 的续跑要么正被另一个进程占用，要么之前有一次续跑中途被打断、留下了一个未完成的记录。这两种情况都**不会**自动重试或超时失效，需要人工确认实际发生了什么之后再决定下一步（而不是去删除任何 claim 文件，或者改用普通的 `resume` 命令绕过这个检查——`resume` 命令本身也会做同样的检查，不会被用来绕开）。

### 4e. 查询与诊断（只读）

```bash
# 列出所有 Task 下的所有 Run
python -m src.main runs

# 查看单个 Run 的时间线（每一轮 LLM 调用/工具调用）、变更、测试结果
python -m src.main inspect <run-id>
```

> 平台里实际上有**三道**不同粒度的人工介入闸门，容易混淆：**计划审批**（4b，执行前，决定"要不要跑这份计划"）、**变更审核**（4c，执行后，决定"这次 Run 改的东西要不要认"）、**工具调用审批**（4d，执行中，决定"这一次具体的工具调用能不能做"）。还有第四道**运行时审批**（计划调度中某一步失败且被分类为 `BLOCKED` 时触发，持久化在 `tasks/<task-id>/runtime_approval.json`），目前完全没有接 CLI，只能通过代码/测试直接调用，见第二部分"未来计划"。

## 5. 项目结构

```
src/
├── models.py                  # 领域模型：TaskDefinition / RunDefinition / AgentDefinition / ...
├── repositories.py             # 持久化层：读写 JSON/Markdown/JSONL 文件（没有数据库）
├── run_service.py              # 编排一次 Run 的完整生命周期（execute/resume/resume_after_approval）
├── run_query_service.py        # 只读 query side：list_runs()/inspect_run()
├── llm_executor.py             # LLMRunExecutor：多轮工具调用循环，返回 LLMRunResult
├── llm_agent_run_executor.py   # 把 Task/Run/Agent 接入 LLMRunExecutor 的适配层
├── run_events.py               # events.jsonl 的实时写入机制（RunEventSink 协议）
├── llm/                        # Provider 无关的请求/响应类型 + Anthropic 具体实现
├── domain/tools/                # ToolDefinition / ToolCall / ToolResult
├── domain/events/                # RunEvent / EventRepository / TimelineBuilder
├── services/tools/                # 工具调度、策略、受限测试执行、七个工具的 handlers
├── review/                      # Run 级人工审核：ChangeSnapshot / review_policy / ReviewService
├── approval_*.py / tool_approval_*.py / run_continuation_*.py
│                                 # 工具调用级人工审批闸门 + Run 续跑 checkpoint（见第一部分 4d）
├── run_service_composition.py  # 这道闸门唯一的生产组装入口（CLI 命令都经过这里，不各自重复拼装）
├── schema_aware_tool_input_previewer.py  # 按工具 schema 手工审查过的安全预览，拒绝回退到整体 dump
├── process_file_lock.py        # 基于 fcntl.flock 的进程级文件锁，按 run_id 互斥
├── agent_registry.py / message_router.py        # Agent 发现 + 消息投递
├── task_plan.py / task_dependency_resolver.py / task_scheduler.py
│                                 # TaskPlan 模型 + 依赖排序 + 调度 + 重试
├── agents/                       # Task-Scoped Agent 生命周期：Template/TaskAgent/Registry/...
├── context/                      # ContextSelector/ContextTrimmer（静态上下文）+ history/（对话历史压缩）
├── planning/                     # Planner 协议、ClaudePlanner、PlanValidator、PlanRepairLoop、...
├── recovery_*.py / execution_checkpoint*.py / runtime_approval_*.py
│                                 # 计划执行失败后的恢复决策链（RETRY/REPAIR_PLAN/REQUEST_APPROVAL/ABORT）
└── cli/                          # 纯展示层：格式化字符串，不 print、不含业务逻辑
```

配置与数据目录：

```
agents/<agent-id>/
├── agent.json / system-prompt.md / tool-policy.json

src/config/
├── test_policy.json       # run_test 的命令白名单
└── approval_policy.json   # 工具调用审批规则（默认空规则列表，见第一部分 4d 的配置示例）

tasks/<task-id>/
├── task.json / background.md / plan.json / approval.json / runtime_approval.json / checkpoint.json
├── approvals/<approval-id>/
│   ├── request.json / resolution.json   # ApprovalRequest / 人工决定
│   └── application.json                 # ApprovalApplicationService 的执行结果（claim+outcome）
└── runs/run-NNN/
    ├── run.json / input.md / output.md / summary.md
    ├── approval_rules.json      # 这个 Run 启动时生效的审批规则快照（续跑读这个，不读实时配置）
    ├── checkpoint.json          # 暂停时刻的 RunContinuationCheckpoint（对话消息+待处理工具调用）
    ├── continuation_attempts/<approval-id>.json  # 每一次 resume-after-approval 续跑的 claim+结果
    ├── continuation.lock        # 该 Run 的进程级文件锁（fcntl.flock，不是数据文件）
    ├── events.jsonl            # 每轮审计事件，实时追加
    └── change_snapshot.json    # ChangeSnapshot（review 命令读这个）
```

## 6. 跑测试

```bash
.venv/bin/python -m pytest tests/ -v
```

> `pytest` 需要在装了 `anthropic`/`python-dotenv` 的同一个环境（`.venv`）里跑，否则涉及 Anthropic Provider 的测试会因为 `ModuleNotFoundError` 无法 collect。

## 7. 如何确认一次真实工具调用确实跑通了

单元测试用的都是 `FakeProvider`，证明不了对真实 Anthropic API 的某次 Run 确实发生了工具调用——模型的最终回答文本本身不是可信证据。由弱到强的验证方法：

1. **内容交叉核对**：把模型声称的工具输出和自己手动跑一遍的结果对比（例如 `ls -a .` 对比 `list_files` 的结果）。
2. **设计"强制依赖"任务**：让后一步工具调用的参数必须依赖前一步的真实返回结果，且这个结果模型不可能提前猜到（例如"列出目录后按字母序取第 N 个文件再读取"，N 要跨过运行时才存在的 `__pycache__/`）。
3. **临时加 round 级别日志**：在 `LLMRunExecutor.execute()`（`src/llm_executor.py`）的循环里临时打印每一轮的 `response.stop_reason`/`tool_calls`——这是 API 原始字段，模型编不出来。验证完记得删掉。
4. **Anthropic 控制台**：https://console.anthropic.com 的 Usage/Logs 页面能看到这个 API Key 每次请求是否真的带了 `tools`、返回是否含 `tool_use`——独立于本项目代码之外的第三方证据。

最可靠的组合是 2 + 3。这套方法已经用来验收过 `read_file`→`patch_file`→`run_test` 的完整自主修复循环（`tasks/task-run-test-loop` 的 run-001：故意写错 `add()` 让测试失败，只告诉模型"有个测试失败了，修好它"，模型自主读文件、定位 bug、patch、跑测试验证，全程无人提示答案）。

---

# 第二部分：项目现状

## 已完成

| 阶段 | 内容 |
|---|---|
| **工具调用基础**（5B） | `list_files`/`read_file`/`git_status`/`git_diff` 四个只读工具；`PathGuard` 做仓库边界防护；`LLMRunExecutor` 实现多轮"请求模型→执行工具→喂回结果→再请求"循环（`max_tool_rounds`/`max_total_tokens` 两道保险）；`events.jsonl` 实时审计（`llm_response`/`tool_call`/`tool_result`/`run_completed`/`run_failed`）；Run 状态机扩展出 `interrupted`/`failed`，`resume` 命令可从崩溃状态创建新 Run 重试。 |
| **写入能力与自主修复闭环**（5C） | `write_file`（create/overwrite，原子写入+sha256）、`patch_file`（唯一匹配文本替换，共享同一写入内核）、`run_test`（白名单命令，`shell=False`，测试失败不算工具失败）三个工具，只对 `agent-coder` 开放；`file_mutation` 审计事件；**Run 级人工审核**——`ChangeSnapshot` + `awaiting_review` 状态 + `review` 命令（approve/reject）；只读的 **query side**——`RunQueryService` + `runs`/`inspect` 命令，和执行/审核的 command side 完全分离。真实 API 端到端验收过多次（包括完整的 读文件→改代码→跑测试→确认通过 闭环）。 |
| **任务编排**（5D） | `ManagerAgent` 把请求拆成带依赖关系的 `TaskPlan`；`PlanValidator` 校验（未知 Agent/未指派/依赖缺失/环依赖）；**Plan 级人工审批**——`plan`/`plans`/`approve-plan`/`reject-plan` 命令；`TaskDependencyResolver` 按依赖拓扑排序成"轮"，`TaskScheduler` 轮内并行、轮间串行调度，失败经 `RetryManager`/`RetryPolicy` 重试，依赖未成功的 step 直接 `SKIPPED`。 |
| **Task-Scoped Agent 架构**（5E-4） | 把"可复用的 Agent 资产"（`AgentTemplate`/`AgentDefinition`，全局持久）和"这个 Agent 当前属于哪个 Task"（`TaskAgent`，Task 内临时成员关系）拆成两个独立生命周期；四条不变量冻结在 `docs/architecture/agent_lifecycle_policy.md` 并有回归测试锁定；`MessageRouter` 作为执行期第二道防线，拒绝向"已不再属于这个 Task"的 Agent 投递消息。 |
| **Claude 结构化规划 + 计划自修复**（5E-1~5E-3） | `ClaudePlanner`（真正调用模型生成结构化 `TaskPlan`，满足与 `RuleBasedPlanner` 相同的 `Planner` 协议，已有单测+集成测试，**但尚未被设为默认 Planner**，需显式注入）；`PlanRepairLoop`——计划校验不通过或执行期失败时，自动生成修复请求、重新规划、再校验，最多 `max_attempts` 次。 |
| **静态上下文优化** | `ContextSelector`/`ContextTrimmer`/`ContextBudget`——用关键词重叠给文件打分选取相关上下文，替代了早期硬编码的固定 5 个文件；配合 **History Compression**（对话历史压缩，见 `src/context/history/`）解决多轮工具调用把上下文越滚越大的问题。 |
| **执行恢复与重规划**（5E-5） | `FailureClassifier`→`RecoveryPlanner`→`RecoveryOrchestrator`→`RecoveryExecutor` 的完整失败决策链（`TEMPORARY_ERROR`→重试，`PLAN_ERROR`→重新规划，`BLOCKED`→人工审批，`FATAL`→放弃）；运行时审批闸门（`runtime_approval.json`）；`TaskPlanResumeService` 从检查点剔除已完成 step 并改写依赖继续调度。整条链路有集成测试覆盖，**但尚未接入任何 CLI 命令**，只能被代码/测试直接调用。 |
| **工具调用级人工审批闸门 + Run 续跑**（5E-5D-6） | 见第一部分 4d 的完整使用说明。摘要：`RuleBasedToolApprovalPolicy`（`ApprovalRule`：工具名+风险等级+原因，来自 `src/config/approval_policy.json`，经 `approval_policy_config.py` 全量校验）判断某个 `ToolCall` 是否需要人工批准；命中规则时 `ToolApprovalGate` 在工具调用循环里拦截，创建 `ApprovalRequest` 并把暂停时刻的完整上下文存进 `RunContinuationCheckpoint`（`run_id` 维度，和计划级的 `ExecutionCheckpoint`——`task_id`/`plan_id` 维度——是两个不复用的独立模型），Run 状态变成 `waiting_for_approval`；`approve/reject/modify/cancel-tool-call` 四个命令只记录决定（`ApprovalDecisionService`），`list/show-tool-approval` 提供只读查询（`SchemaAwareToolInputPreviewer` 按每个工具的 schema 手工审查过哪些字段安全可展示，未知工具/未审查字段一律显式说明"已省略"，绝不回退到 `repr()`/`json.dumps()` 整个输入）；`resume-after-approval <run-id> <approval-id>` 驱动 `ApprovalContinuationPreparationService`（四者一致性校验）+`ApprovalApplicationService`（真正执行/跳过工具）继续同一个 Run，可能再次暂停产生新的 `ApprovalRequest`，也可能正常结束；`RunContinuationAttemptRepository`+`process_file_lock.py`（`fcntl.flock` 进程级文件锁，按 `run_id` 互斥，和持久化的 `CLAIMED`/`COMPLETED` 记录分别负责"排除同时发生的竞争"和"阻止进程崩溃后被自动重放"两件事）保证同一个 Run 的续跑不会被重复或绕过；`run_service_composition.py` 是唯一的生产组装入口，`ApprovalApplicationService` 用的 `ToolExecutor` 和真正续跑这个 Run 的执行器用的是同一套 workspace/ToolPolicy/工具注册表；`_LazyLLMProvider` 把 Anthropic 凭据校验推迟到真正发起请求的那一刻，所以 `--help`、只读查询、记录决定、重放已完成的续跑、CANCEL 都不需要配置 API Key。 |

共约 **1500+ 个测试**（`pytest tests/` 全部通过；`PATH="$PWD/.venv/bin:$PATH" .venv/bin/python -m pytest tests/` 保证子进程里的 `run_test` 工具也能找到 `python`，否则会有几个 subprocess 相关测试因为环境 PATH 问题失败，和代码本身无关）。

## 未来计划 / 已知限制

- 运行时审批（`runtime_approval.json`，计划执行中 `BLOCKED` 失败触发）还没有对应的 CLI 命令——现在平台一共有三道人工闸门接了 CLI（计划/变更/工具调用），这一道还没有。
- 执行恢复层（`RecoveryOrchestrator`/`RecoveryExecutor`）完全没有接入 CLI；`RecoveryAction.ABORT` 目前静默跳过，没有真正的终止逻辑；没有 `CheckpointWriter`——没有生产代码会在计划执行后自动生成 `ExecutionCheckpoint`，恢复路径可用但触发它需要手工构造检查点。
- `ClaudePlanner` 已实现、测试齐全，但 `ManagerAgent` 默认仍是 `RuleBasedPlanner`，没有生产路径会自动用上真正的模型规划。
- `patch_file` 只能替换单个精确匹配的文本块，不支持一次应用多段 unified diff；`write_file` 没有 append 能力。
- 工具调用审批闸门的持久化（claim 文件、continuation attempt 记录）都只用普通文件写入（临时文件+`rename`），没有 `fsync`——能保证进程被杀掉/崩溃后状态不丢，不能保证断电那一刻正在写的文件不丢。一旦一次续跑在"进程持有锁"和"标记完成"之间被打断，会留下一条 `CLAIMED` 记录**永久**阻塞自动续跑（这是故意的保守设计，不会自动过期或被接管），需要人工确认实际发生了什么、再决定怎么处理——目前没有提供任何"删除/接管一个 CLAIMED 记录"的命令或流程。
- 进程级文件锁（`process_file_lock.py`）基于 POSIX 的 `fcntl.flock`，只在 Linux/macOS 上有效；在不支持的平台上会显式报错退出，不会静默退化成"不加锁"。
- `run_test` 只能跑预先注册的整套命令（如 `pytest -q`），不能只跑某一个测试文件/函数。
- 没有数据库，没有通用的多进程并发写保护（本次改动里的 `process_file_lock` 只解决了续跑场景的一个具体竞态，不是通用方案）。
- `review` 命令没有 Reviewer Agent，看不到具体 diff 内容（`ChangeSnapshot.diff_path` 恒为 `null`，没有代码生成 `diff.patch`）。
- `RuleBasedContextSizeEstimator` 只按字符数量级估算、只看元数据不读文件内容，静态上下文裁剪是"按文件数量丢文件"，不是精确按 token 数截断。
- `AgentTemplateRepository` 目前纯内存实现，没有持久化，进程重启就丢。
- 只支持 Anthropic 一家 LLM provider；`LLMProvider` 协议本身 provider 无关，理论上可扩展支持多个 provider/多个 API key（尚未开始）。
- 容器化 Agent Runtime 原型（`runtime/` + `scripts/`，更早期的技术验证草稿）与主执行链路尚未整合。
