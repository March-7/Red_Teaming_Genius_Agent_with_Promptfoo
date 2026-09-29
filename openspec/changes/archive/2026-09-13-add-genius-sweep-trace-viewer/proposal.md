## Why

当前 sweep 的轨迹分散在 `genius_trace.jsonl`、`session_lifecycle.jsonl`、`eval.json`、`oracle.jsonl` 和 `summary.md` 中，缺少一个直观的本地浏览界面。为了像 Genius 网页端那样查看对话、工具调用和 approval 过程，需要一个只读的 trace viewer，而不是依赖 live Genius session。

## What Changes

- 新增本地 Genius sweep trace viewer，只读、离线、不访问 Genius。
- 借鉴 Inspect AI log viewer 的信息组织方式：
  - 左侧 run / plugin / session 列表
  - 中间对话时间线
  - 右侧 trace / tool / approval / oracle 详情
  - 顶部过滤、排序和搜索
- 支持按以下维度聚合和过滤：
  - `run_id`
  - `group_id`
  - `plugin_id`
  - `upstream_session_id`
  - `request_id`
  - `outcome`
  - `tool_name`
  - `confirmation_id`
- 支持 JSONL 原始事件展开查看。
- 支持将 tool call、approval、oracle 和 Promptfoo eval 结果与对话时间线对齐。
- 支持深链和浏览器刷新后保留当前视图状态。
- 在基础 viewer 可用后，继续做一轮面向真实 trace 的前端体验优化，使时间线呈现更接近
  Genius 网页端的对话、工具调用和 approval 过程。
- 不修改 Genius shim 的审批行为。
- 不引入 live Genius 前端或 Genius 私有 API。

## Capabilities

### New Capabilities

- `genius-sweep-trace-viewer`: 定义本地只读 trace viewer 的数据索引、对话时间线、tool call 视图、approval 视图、oracle 视图、过滤、深链、前端呈现质量和安全边界。

### Modified Capabilities

无。本 change 只新增 viewer，不修改 `genius-controlled-approvals` 或
`genius-plugin-sweep` 的既有行为。

## Impact

- 新增本地 viewer 入口命令。
- 新增 viewer 前端或静态页面。
- 新增 trace 索引和聚合逻辑。
- 新增 viewer 相关测试。
- 不修改 Genius shim、Promptfoo provider 或 OpenAI-compatible target 协议。
