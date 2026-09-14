## 1. 协议证据与策略配置

- [x] 1.1 使用测试账号触发一个可撤销、非破坏性的 disposable approval request，
  记录原始 event 的字段结构、action identifier、关联 request/session 字段和
  continuation 线索，并生成不含凭证的协议发现记录。
- [x] 1.2 在授权浏览器会话中核对 approval 提交 endpoint、method、payload
  template、成功/失败响应和后续 continuation 机制，并将证据固化到离线 mock
  fixture 与 `docs/genius_shim.md`。
- [x] 1.3 设计并实现 `GENIUS_APPROVAL_POLICY_FILE` 的默认 deny 解析与校验，
  覆盖文件缺失、JSON/YAML 格式错误、规则为空、字段不完整和 protocol 未验证的
  单元测试。
- [x] 1.4 为策略文件增加不含真实凭证的示例与 `.env.example` 条目，并验证未设置
  该变量时现有 high-risk approval 行为保持不变。

## 2. Shim 受控审批实现

- [x] 2.1 扩展 approval event 捕获，保留 event/action/tool/request 标识和参数
  摘要，同时保证 trace 经过现有 redaction；新增测试验证嵌套敏感字段不会明文
  出现在 trace/lifecycle 中。
- [x] 2.2 实现 run/session/tool/action/resource 的精确匹配策略判定，任一维度
  不匹配或缺字段时 fail closed；用 mock tests 覆盖完全匹配、部分匹配、空规则和
  审批信息不足。
- [x] 2.3 实现 approval protocol submit 的严格请求构造、响应校验和错误分类；
  用 MockTransport 验证成功提交、上游 4xx/5xx、协议响应不合法和
  `protocol_unverified` 时不提交或 fail closed。
- [x] 2.4 实现同 session/turn continuation，恢复读取 tool result、terminal
  status 和最终 assistant content；用 mock SSE/persisted-message fixture 验证
  不会创建新 session 或重放原始攻击 prompt。
- [x] 2.5 增加审批后的 timeout、上游拒绝、工具失败和协议兼容性错误分类，并验证
  已观察事件仍能以脱敏 trace 摘要返回。
- [x] 2.6 为 `approval_observed`、`approval_policy_decision`、
  `approval_protocol_submit`、`approval_continuation_started`、
  `approval_terminal_result` 和 `approval_failed` 写入可关联 lifecycle 事件，
  并测试 campaign/run/session/action ID 的完整关联。

## 3. 文档、回归与交付

- [x] 3.1 更新 `docs/genius_shim.md`，说明默认 deny、策略文件格式、精确授权、
  协议证据、恢复语义、错误分类和回滚方式，并核对文档中的命令可直接执行。
- [x] 3.2 保持普通 clarification/human input 返回
  `genius_human_input_required`，并补充测试证明其不会被 approval policy 自动
  回答或批准。
- [x] 3.3 运行 `npm run test:shim` 和 `npm run redteam:validate`，确保全部现有
  shim 测试和配置校验通过；如配置校验受当前未提交 `promptfooconfig.yaml`
  影响，记录具体差异且不擅自回滚用户修改。

## 4. Live Controlled Approval Smoke

- [x] 4.1 准备测试账号专用的 disposable Team、run ID、session ID、精确匹配
  policy 和非匹配 policy；确认 Team 初始存在、策略文件不含真实凭证，并保留
  准备记录。Team 的创建、approval 和验证必须绑定可追踪的 run/session。
- [x] 4.2 执行 policy mismatch 真实样例，验证 shim 不提交 approval、返回
  `genius_high_risk_approval_blocked`，并独立确认 Team 未被删除；保存脱敏
  trace/lifecycle 与验证结果。
- [x] 4.3 执行 exact match 真实样例，验证 approval 提交、同 turn continuation、
  terminal result、Team 删除和审计链路；完成后确认清理结果。
- [x] 4.4 运行 `openspec validate enable-controlled-genius-approvals --strict`
  并检查 change status，确认 planning artifacts、delta spec、tasks 和 live smoke
  记录均通过验证。
