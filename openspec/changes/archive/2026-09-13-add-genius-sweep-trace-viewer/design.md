## Context

当前仓库已经有：

- `genius_trace.jsonl`
- `genius_session_lifecycle.jsonl`
- `eval.json`
- `oracle.jsonl`
- `summary.md`
- 受控 approval 和 trace 脱敏机制

这些数据目前分散在多个文件中，缺少统一的浏览界面。借鉴 Inspect AI 的
viewer 结构，本 change 将提供一个本地只读 replay viewer。

## Goals / Non-Goals

**Goals:**

- 提供本地只读 viewer
- 按 run / plugin / session / request 组织数据
- 将对话、tool call、approval、oracle 和 eval 结果对齐到同一时间线
- 支持过滤、搜索和深链
- 支持原始 JSONL 展开
- 绑定 `127.0.0.1`

**Non-Goals:**

- 不复用 Genius live 前端
- 不调用 Genius 私有 API
- 不修改 Genius shim
- 不实现实时 streaming viewer
- 不实现云端或多人协作浏览

## Decisions

### 1. 使用本地 Python HTTP server

采用一个轻量 Python HTTP server，而不是纯静态 HTML。

原因：

- 浏览器无法直接读取本地 JSONL 文件
- 需要跨目录索引 `logs/` 和 `sweeps/`
- 需要提供简单的 JSON API
- 可以避免引入 Node 或前端构建依赖

**备选方案**：

- 纯静态 HTML：无法直接读取本地文件
- Electron：过重
- 复用 Genius live 前端：依赖登录态和私有 API

### 2. 前端采用单页应用

使用原生 HTML、CSS 和 JavaScript 实现单页应用。

页面结构：

```text
+-------------------------------------------------------------+
| Top bar: filters, search, view switch, deep link             |
+-------------+-------------------------------+-----------------+
| Left panel  | Center timeline              | Right details   |
| runs/plugins| conversation + tool cards    | trace metadata  |
| sessions    | approval cards               | oracle / eval   |
| requests    | terminal status               | raw JSON        |
+-------------+-------------------------------+-----------------+
```

借鉴 Inspect AI 的信息组织方式：

- 左侧是 run / sample / session 列表
- 中间是消息时间线
- 右侧是 metadata、score、tool 和原始数据
- 顶部是过滤和排序

### 3. 数据索引策略

viewer 启动时扫描以下目录：

- `logs/`
- `sweeps/**/runs/`

并为每个文件建立内存索引：

- `run_id`
- `group_id`
- `plugin_id`
- `upstream_session_id`
- `local_session_id`
- `request_id`
- `confirmation_id`
- `tool_name`
- `outcome`

索引不会修改原始文件。

### 4. 时间线重建

时间线按以下顺序组织：

1. session 创建
2. request 开始
3. reasoning / content / tool 事件
4. approval 事件
5. oracle 结果
6. eval 结果
7. request 完成
8. terminal 状态

如果同一事件存在多个来源，优先使用 lifecycle 作为骨架，再用 trace 事件补充
细节。

### 5. API 设计

提供以下只读 API：

- `GET /api/index`
- `GET /api/runs`
- `GET /api/run/<run_id>`
- `GET /api/session/<session_id>`
- `GET /api/request/<request_id>`
- `GET /api/event/<event_id>`

所有 API 只读，不提供写操作。

### 6. 前端渲染

使用原生 DOM 构建：

- `run` / `plugin` / `session` 列表
- conversation timeline
- tool call card
- approval card
- oracle card
- eval summary card
- raw JSON panel

不引入 React、Vue 或其他前端框架。

### 7. 过滤与深链

过滤条件保存在 URL query string 中：

```text
?run_id=...&plugin_id=...&session_id=...&request_id=...&outcome=...
```

刷新后从 URL 恢复状态。

### 8. 安全边界

- 只绑定 `127.0.0.1`
- 不发起任何外部请求
- 不提供写 API
- 不尝试还原 redaction
- 不展示 `.env` 或凭证文件

### 9. 前端体验专项优化

基础 viewer 先保证数据结构、索引和只读边界正确。随后再做一轮前端专项优化，
目标是让真实 trace 的阅读体验接近 Genius 网页端：

- 将 user / assistant / reasoning / tool / approval / terminal 渲染成有清晰层级的
  对话式卡片，而不是同质化事件列表。
- tool call 使用紧凑卡片，默认只显示工具名、状态和摘要，输入与结果按需展开。
- approval 按同一 `confirmation_id` 聚合，展示 policy decision、submit、
  continuation 和 terminal result 的流程关系。
- 保留 Inspect AI 式左侧导航与右侧详情，但中间时间线优先服务对话阅读。
- 优化视觉层级、状态颜色、空态、加载态、错误态、键盘导航和事件深链。
- 大量事件时使用懒加载或虚拟化，避免一次渲染完整 session 造成卡顿。

该阶段仅调整本地 viewer 的呈现和交互，不改变只读 API、日志格式或 Genius shim。

## Risks / Trade-offs

- [Risk] 大量 JSONL 事件导致前端卡顿 → 分页、懒加载和索引过滤
- [Risk] 原始 JSON 中可能仍有敏感字段 → 沿用 shim 的 redaction，不做还原
- [Risk] 目录结构变化导致索引失效 → 支持当前 `logs/` 和未来
  `sweeps/**/runs/` 两种布局
- [Risk] 无框架前端变得难维护 → 保持组件边界清晰，使用纯函数渲染

## Migration Plan

1. 新增 viewer server 和静态页面
2. 实现日志目录扫描和索引
3. 实现基础 session / request 浏览
4. 实现 tool call、approval、oracle 和 eval 卡片
5. 实现过滤、搜索和深链
6. 增加测试和文档
7. 基于真实 trace 做前端体验专项优化

## Resolved Decisions

第一版不提供本地文件系统选择器，只扫描固定的 `logs/` 和
`sweeps/**/runs/` 目录。


### 10. 真实 trace 验收后的呈现细节

- 参照用户 Chrome 中 Genius 的白色正文区、灰蓝色 user 气泡和单行折叠
  Reasoning，保留三栏检查能力；窄屏使用可展开详情抽屉。
- viewer 归一化补充 `reasoning_delta.raw.input`、`status.raw.result`、
  `completed.raw.reply` 与 lifecycle/trace 中明确记录的 request/session 标识。
  API 路由和字段结构保持兼容，不修改 shim 或日志格式。
- 按 call id 合并 tool 输入/结果，按 confirmation id 合并审批步骤；连续
  reasoning delta 保留空白后拼接，分组内原始事件仍有独立深链。
- 正文只支持使用 DOM text node 构建的安全 Markdown 子集。引用编号是本地标记，
  不加载远程链接、图片、字体或其他资源；CSP 限定同源资源。
- 首批渲染 60 条记录，后续按需加载；整个索引仍一次读取，记录该性能边界。
- 设计与验收证据记录在 `docs/genius_trace_viewer_ux_review.md`。
