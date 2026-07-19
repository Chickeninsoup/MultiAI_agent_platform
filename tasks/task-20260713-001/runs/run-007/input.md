测试本次新增的工具调用能力。

请**实际调用**你现在拥有的工具（list_files、read_file、git_status、git_diff），不要凭已有知识或猜测作答：

1. 用 `list_files` 列出 `src/services/tools/` 目录下的文件。
2. 用 `read_file` 读取 `src/services/tools/tool_executor.py`，确认其中是否定义了 `ToolExecutor` 类，并说明它的 `execute` 方法大致做了什么。
3. 用 `git_status` 查看当前仓库工作区状态，报告有哪些文件被修改或新增。
4. 用 `git_diff` 查看当前未提交改动的内容摘要（如果有改动的话）。

在最终回答中，请按步骤说明：
- 你调用了哪个工具、传了什么参数；
- 工具实际返回了什么（可以摘要，不需要全文粘贴）；
- 基于工具返回结果得出的结论。

如果某一步工具调用失败或返回错误，也如实报告，不要编造结果。
