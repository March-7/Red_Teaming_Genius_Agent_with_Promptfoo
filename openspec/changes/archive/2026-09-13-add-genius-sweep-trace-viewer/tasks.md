## 1. Viewer Server and Data Index

- [x] 1.1 Create `viewer/server.py` with a read-only Python HTTP server that
  binds only to `127.0.0.1`; verify startup and shutdown tests pass.
- [x] 1.2 Implement source discovery for `logs/` and
  `sweeps/**/runs/`; verify that both global logs and future run directories
  are indexed.
- [x] 1.3 Implement JSONL parsing and an in-memory index keyed by `run_id`,
  `group_id`, `plugin_id`, `upstream_session_id`, `local_session_id`,
  `request_id`, `confirmation_id`, `tool_name`, and `outcome`; verify with unit
  tests using synthetic JSONL fixtures.
- [x] 1.4 Implement read-only API routes for `/api/index`, `/api/runs`,
  `/api/run/<run_id>`, `/api/session/<session_id>`, and
  `/api/request/<request_id>`; verify each route with unit tests.

## 2. Conversation Timeline

- [x] 2.1 Implement event normalization that merges lifecycle and trace events
  into a single ordered timeline; verify ordering with synthetic session data.
- [x] 2.2 Implement conversation timeline rendering for user messages,
  assistant replies, reasoning, tool calls, approvals, errors, and terminal
  status; verify with a browser screenshot or DOM test.
- [x] 2.3 Implement request alignment that joins trace, lifecycle, oracle, and
  eval results to the same request view; verify with synthetic cross-file
  fixtures.

## 3. Tool Call, Approval, Oracle and Eval Views

- [x] 3.1 Implement tool call cards that display `tool_name`, `tool_input`,
  `tool_result`, `status`, `request_id`, and `upstream_session_id`; verify with
  unit and DOM tests.
- [x] 3.2 Implement approval cards that display `confirmation_id`, `action`,
  `tool`, `resource`, policy decision, protocol response, continuation, and
  terminal result; verify with synthetic approval events.
- [x] 3.3 Implement oracle and eval cards that display side-effect evidence and
  Promptfoo results; verify with synthetic `oracle.jsonl` and `eval.json`.
- [x] 3.4 Implement raw JSONL inspection with formatted JSON, copy support,
  and collapsed-by-default layout; verify with unit and browser tests.

## 4. Filtering, Search and Deep Links

- [x] 4.1 Implement filters for `run_id`, `group_id`, `plugin_id`,
  `upstream_session_id`, `request_id`, `outcome`, `tool_name`, and
  `confirmation_id`; verify each filter with unit tests.
- [x] 4.2 Implement text search across event text, tool input, tool result,
  and metadata; verify search results with synthetic data.
- [x] 4.3 Implement URL query state and deep links that restore the current
  run, session, request, filters, and scroll position; verify with browser
  refresh tests.

## 5. Frontend, Tests and Documentation

- [x] 5.1 Build the single-page frontend with a left run/plugin/session list,
  center timeline, right detail panel, and top filter bar; verify layout with
  desktop and narrow viewport screenshots.
- [x] 5.2 Add tests for server startup, source discovery, JSONL parsing, API
  routes, timeline ordering, filtering, search, and deep links; verify the full
  test suite passes.
- [x] 5.3 Add documentation for viewer startup, supported data sources,
  navigation, filtering, search, raw JSON inspection, and local-only security
  boundary; verify documented commands run successfully.
- [x] 5.4 Run `npm run test:shim`, `npm run redteam:validate`, and
  `openspec validate add-genius-sweep-trace-viewer --strict`; verify all checks
  pass and record any unrelated pre-existing failures without masking them.

## 6. 前端体验优化

- [x] 6.1 使用真实 approval session 和 tool-call session 完成设计审查，记录
  视觉层级、可读性、密度、分组、导航、空态和响应式问题。
- [x] 6.2 将时间线改造为 Genius 风格对话：区分 user 和 assistant，折叠 reasoning，
  紧凑展示 tool call，聚合 approval 流程，清晰展示 terminal 状态。
- [x] 6.3 完善事件深链、键盘导航、可见选中状态、上下文详情更新和长 session 懒加载。
- [x] 6.4 统一字体、间距、状态颜色、badge 和图标；提供深浅主题，以及加载、空态和错误态。
- [x] 6.5 使用真实 trace 完成浏览器视觉 QA，保留优化前后截图，验证键盘和深链行为，
  并重跑 `npm run test:viewer`。
- [x] 6.6 确认本轮优化保持 local-only、read-only、无外部网络和 redaction 边界。

验收记录：`docs/genius_trace_viewer_ux_review.md`。截图与机器验收结果位于
Git 忽略的 `logs/viewer-qa/`。补充真实多轮验收记录位于
`logs/viewer-multiturn-20260913/summary.md`：4 轮、15 次调用、6 种工具，
桌面、窄屏、深链和 11 项 viewer 测试通过。
