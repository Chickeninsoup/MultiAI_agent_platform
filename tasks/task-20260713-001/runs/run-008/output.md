# Run Output

- Task ID: `task-20260713-001`
- Run ID: `run-008`
- Agent ID: `agent-general`
- Provider: `anthropic`
- Model: `claude-sonnet-5`
- Input tokens: `12320`
- Output tokens: `482`

## Agent Response

该平台目前核心组成包括:1) Agent 模块(agents/目录下的 agent.json、系统提示词、工具策略,独立于任务和容器);2) Task 模块(tasks/目录下的 task.json、background.md,记录任务状态与背景);3) Run 模块(每个任务下 runs/子目录,含 run.json、input/output/summary.md,记录执行状态与产出);4) 数据模型层(models.py 定义 Agent/Task/Run 结构);5) 仓储层(repositories.py 负责读写 JSON 与文本文件);6) 执行层(execution.py、run_service.py、executor_factory 及 LLM 执行器,协调上下文构建与运行);7) CLI 入口(main.py,提供 list/run 命令)。
