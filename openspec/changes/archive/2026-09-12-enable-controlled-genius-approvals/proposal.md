## Why

当前 Genius shim 在收到 high-risk approval event 后默认中断并返回
`genius_high_risk_approval_blocked`，因此只能记录“Agent 请求了危险动作”，不能
验证用户批准后工具、权限层和 sandbox 是否真正阻止了越界副作用。为了支持后续
部署前 red-team sweep，需要一个可审计、默认拒绝、可精确授权的受控审批续跑机制。

## What Changes

- 保留默认 deny 行为：未显式配置授权策略时，high-risk approval 仍返回
  `genius_high_risk_approval_blocked`。
- 完整捕获 approval event 中可用于提交决策的 event/action/tool 标识、参数摘要和
  关联上下文，并继续对敏感字段做 redaction。
- 新增配置化的 approval policy，按 run、session、tool、resource 或 action 的精确
  匹配决定 approve/deny；不满足匹配时 fail closed。
- 通过经过证据核实的 Genius 私有审批协议提交允许的 approval，并在同一
  upstream session 和 turn 语义下继续读取执行结果。
- 将审批前请求、审批决策、审批提交、恢复执行、terminal result、超时和错误写入
  trace/lifecycle 记录，保持与 Promptfoo campaign ID 的关联。
- 为协议发现、受控恢复、默认拒绝、权限边界和错误分类补充离线 mock 测试与文档。
- 增加 live controlled approval smoke validation：在测试账号中创建并删除
  disposable Team，验证 fail closed 和 approve/continue 两条关键路径。

## Capabilities

### New Capabilities

- `genius-controlled-approvals`: 定义 Genius shim 对 human approval 的捕获、
  策略判定、受控提交、同 turn 恢复、终态确认、失败分类和审计要求。

### Modified Capabilities

无。仓库当前没有已归档的主 spec。

## Impact

- 影响 `shim/genius_service.py` 的 approval event 捕获、请求循环和 trace 结构。
- 影响 `tests/test_genius_shim.py` 的 approval/human-input 行为测试。
- 影响 `docs/genius_shim.md` 的安全语义、配置和验证说明。
- 影响 `.env.example` 中新增的默认 deny 配置项；真实凭证仍保留在 Git-ignored
  `.env` 中。
- 不修改 Promptfoo sweep 配置、不创建 summary generator、不引入自定义 plugin，
  也不执行 broad destructive 测试。
- live Genius 请求仅限测试账号上的 1-2 个 disposable approval smoke case；不覆盖
  真实用户/租户数据、不发布 Skill、不创建持久调度、不外传数据。
