# Trace Viewer 视觉与交互验收

验收日期：2026-09-13。对应 change：`add-genius-sweep-trace-viewer`。

## 参考与真实样本

通过 Chrome 已打开的 Genius 页面核对视觉：白色主阅读区、灰蓝色用户消息、
正文直接呈现 Markdown、折叠 Reasoning、轻量导航。当前可见页面是
“三亚亲子旅游攻略”。只读取了页面显示，未调用 Genius API 或发送新消息。

本地真实样本：

- `logs/live-smoke/`：`project_create_with_team` 工具输入与结果。
- `logs/live-smoke/`：同一 confirmation 的 denied → approved → protocol submit
  → response → terminal result，另有 continuation 记录。
- `sweeps/p0-agent-control/hijacking/runs/`：三亚攻略长回复；该 session 的
  1,243 条原始事件合并为 8 条阅读记录。

## 优化前问题与处理

| 问题 | 处理 |
| --- | --- |
| 所有事件使用同样的边框、灰色标题栏和 metadata，回复没有阅读层级 | user 气泡、assistant 正文、轻量 lifecycle、独立 tool 与 approval 卡片 |
| reasoning 每个 delta 都成为卡片，滚动距离过长 | 按 run/session/request/round 合并连续 delta，默认收起 |
| 真实工具输入编码在 `reasoning_delta.raw.input`，结果编码在 `status.raw.result` | 识别真实 wire 格式，按 call id 合并输入和结果，保留原始事件入口 |
| 最终回复保存在 `completed.raw.reply`，旧视图未展示 | 呈现最终回复的标题、段落、列表、代码、表格和引用编号 |
| 顶部八个过滤器长期挤占空间，窄屏正文排在长导航之后 | 筛选面板按需展开，窄屏保留运行导航和正文，详情改为抽屉 |
| 深链没有 event id，刷新时 session 分支覆盖 request 筛选 | 统一 URL 状态，保存 event/view 和全部过滤条件，支持后退及滚动恢复 |
| 点击事件没有明确选中反馈，右侧上下文不能可靠跟随 | 选中边框、键盘导航、分组内每条原始事件可独立选中 |
| 无清晰错误与加载反馈 | 初始加载提示、空态、API 错误与重试、复制反馈 |
| request 的成功状态可能来自中间 tool status | 按最终 request/approval 结果覆盖中间状态 |

## 浏览器验收

可重跑命令（viewer 需先启动）：

```bash
npm run test:viewer
node tests/viewer_real_trace_qa.cjs
```

`tests/viewer_browser_qa.cjs` 由 Python 测试使用临时离线 fixture 调用，覆盖：

- user / assistant 区分、Markdown、reasoning 折叠、tool 输入结果和 approval 分组。
- 分组内事件链接刷新、键盘导航与唯一选中状态。
- 首屏仅渲染 60 条记录、继续加载、深链定位尚未加载事件。
- session/request/tool 组合过滤与刷新恢复；tool 过滤保留所属请求上下文。
- 390px 窄屏、详情抽屉、深浅主题持久化、空态、失败重试。
- trace 内 HTML、远程图片及链接不成为活动内容，浏览器零外部请求。

`tests/viewer_real_trace_qa.cjs` 使用当前本地真实日志验证工具、审批、长回复，
生成 `logs/viewer-qa/acceptance.json` 与截图。截图含本地日志内容，保持 Git 忽略：

- `before-desktop.png`：优化前的 live-smoke 视图，保留作对照。
- `after-tool-desktop.png`：工具输入与结果。
- `after-approval-desktop.png`：同一 confirmation 的完整审批流程。
- `after-desktop.png`：与 Genius 当前页面对应的长回复排版。
- `after-mobile.png`：390 × 844 窄屏。
- `after-dark.png`：深色主题。

已逐张检查桌面正文、审批、工具、窄屏和深色截图。未出现页面横向溢出，
窄屏可直接阅读正文。浏览器运行无 JavaScript 异常、无外部网络请求。

## 保留的证据边界

- 用户原文缺失时显示“这条日志未记录用户原文”，不从 reasoning 反推用户消息。
- 缺失 tool input/result 显示未记录，不补造调用参数。
- 仅对明确相同 call id 或 confirmation id 的事件分组；原始行仍可单独检视。
- 引用编号保留为本地标记，不访问来源网站；Markdown 是安全子集，不执行 HTML。
- 只绑定 `127.0.0.1`，无写 API；CSP 限制网络资源为本地 origin。
- 不更改 Genius shim、日志内容、审批行为或 provider。此次未运行 live sweep。
- 截图验收验证当前日志规模；初始 API 仍加载整个索引，非百万事件级性能保证。


## 本轮检查结果

- `npm run test:viewer`：11 项通过（包括浏览器综合回归）。
- `npm run test:shim`：40 项通过。
- `npm run redteam:validate`：Configuration is valid。
- `openspec validate add-genius-sweep-trace-viewer --strict`：通过。
- `node tests/viewer_real_trace_qa.cjs`：真实数据验收通过，浏览器异常与外部请求均为 0。
- `git diff --check`：通过。


## 归档前补充验收

2026-09-13 使用独立 Genius session 完成 4 轮真实对话，保存 15 次唯一工具调用、
6 种工具和 4,347 条 trace 记录；完整记录与截图位于 Git 忽略的
`logs/viewer-multiturn-20260913/`。该轮发现并修复原文缺失提示重复和窄屏表格首列
挤压问题，重跑 11 项 viewer 测试及真实对话浏览器验收均通过。


## 2026-09-13 记录重置

用户要求正式 P0 评测前清空测试记录；旧 smoke、viewer 演示、QA 截图和三个 hijacking run 已删除。
上文涉及的历史日志/截图路径不再代表当前存在的文件，测试代码与配置仍保留。
