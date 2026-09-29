
## Context

现有 shim 已经能创建/复用 Genius session、解析 SSE、记录 trace，并在检测到
human approval 时中断；相关行为集中在 `shim/genius_service.py`，现有测试明确
要求 high-risk approval 不被提交。Genius 使用私有 web-product endpoint，没有公开
稳定的审批 API 契约，因此审批提交协议必须先通过受控、可回滚的证据发现来确认。

## Goals / Non-Goals

**Goals:**

- 保持默认拒绝和现有 `genius_high_risk_approval_blocked`/`genius_human_input_required`
  兼容行为。
- 明确 session-scoped workspace 语义：不同 Genius session 对应不同隔离 workspace，
  live smoke 的 Team 创建、approval 和验证必须绑定可追踪的 run/session。
- 支持按 run、session、tool、action/resource 精确授权的高风险审批。
- 在同一 session/turn 中恢复执行，并记录到 terminal result 或失败分类。
- 保留脱敏、可关联的审批审计链路。
- 用离线 mock 测试覆盖默认 deny、策略匹配、恢复执行和错误路径。
- 在 mock 测试通过后，执行 1-2 个测试账号上的 live controlled approval smoke
  case，验证真实 approval 提交、同 turn 恢复和可撤销副作用。

**Non-Goals:**

- 不实现 Promptfoo plugin sweep、summary generator 或自定义 plugin。
- 不执行 broad destructive 测试、Skill 发布、持久调度、数据外传或跨真实用户/
  租户数据操作。
- 不验证产品权限层的最终安全结论；该结论依赖后续独立 oracle 和 sweep。
- 不改变 Promptfoo target 协议或 OpenAI-compatible response 结构。

## Decisions

### 1. 默认 deny，策略文件显式 opt-in

新增本地 Git-ignored 配置入口 `GENIUS_APPROVAL_POLICY_FILE`。文件未设置、路径
不存在、JSON/YAML 解析失败、规则为空或字段不完整时，一律维持默认拒绝。

策略文件包含两部分：

- `rules`: 精确匹配的 allow 规则，必须同时匹配 run/session/tool/action/resource
  等已声明维度。
- `protocol`: 经证据核实的 approval endpoint、method、payload 映射和响应校验
  条件。

这样每插件、每 run 可以独立授权，避免一个全局开关放宽所有危险动作。

**备选方案**: 直接使用 `GENIUS_APPROVAL_MODE=allow`。该方案简单但过宽，无法
满足精确授权和审计要求，因此不采用。

### 2. 审批证据与敏感值分离

`human_input_request` 需要保留提交决策所需的 raw identifier，例如 event id、
action id、tool id 和关联 request id。审计输出时使用现有 redaction/sanitization
机制，只写入脱敏摘要；raw 值仅在内存中用于构造审批请求，不写入日志。

**备选方案**: 继续只保存 event type、status、tool name 和 question。该方案无法
构造唯一审批请求，也不足以复盘，因此不采用。

### 3. 协议先发现、后启用，再执行受控 live smoke

实现前先执行一次受控协议发现：

1. 使用测试账号和可撤销、非破坏性的 disposable action。
2. 记录 approval request 的完整事件结构。
3. 从授权浏览器会话中核对提交 endpoint、method、payload 和响应语义。
4. 将结果固化到 `docs/genius_shim.md` 和 mock test fixture。
5. 只有协议 fixture 与运行时证据一致时才启用 approval 提交。

不得根据猜测的 endpoint 或 payload 自动重试。

mock 测试通过后，执行两个真实 smoke case：

1. **policy mismatch / fail closed**：触发同一个 disposable action，但策略故意
   不匹配。预期不提交 approval，返回 `genius_high_risk_approval_blocked`，且目标
   Team 未被删除。
2. **exact match / approve and continue**：策略只允许该 run、session、tool 和
   disposable Team ID。预期提交 approval、恢复同 turn 执行、收到 terminal
   result，并独立验证 Team 已被删除。

两个 case 都必须使用测试账号、disposable Team、独立状态验证和事后清理；清理失败要
作为 smoke 失败记录，不得静默通过。

**备选方案**: 直接复用 `/chat/stream` 或常见 approval endpoint。该方案容易造成
错误副作用和不可解释的失败，因此不采用。

### 4. 恢复同 session/turn，不重放攻击 prompt

审批成功后，shim 应继续使用 Genius 提供的 continuation 机制，或重新打开与同一
turn 关联的 stream。不能通过重新提交原始用户 prompt 创建新 session 来模拟恢复。

**备选方案**: 将完整攻击 prompt 再次发送到同一 session。该方案会改变事件语义，
无法证明审批后的真实执行链，因此不采用。

补充约束：不要用另一个 session 的文件状态来推断当前 session 的 workspace。若
资源在 session A 创建、在 session B 操作，session B 看到的“不存在”不能
说明 session A 的文件已被清理，也不能说明 sandbox 边界失效。

### 5. 审计阶段显式建模

lifecycle 记录新增阶段：

- `approval_observed`
- `approval_policy_decision`
- `approval_protocol_submit`
- `approval_continuation_started`
- `approval_terminal_result`
- `approval_failed`

每个事件携带 run/session/campaign/tool/action 关联字段，并沿用现有文件锁和
append-only JSONL 行为。

**备选方案**: 只在最终 trace 中记录 outcome。该方案无法区分策略拒绝、协议失败
和恢复失败，因此不采用。

## Risks / Trade-offs

- [Risk] Genius 私有审批协议随产品更新变化 → 使用协议发现 fixture、严格响应校验
  和 fail closed；协议不匹配时返回 compatibility error。
- [Risk] raw approval identifier 意外写入日志 → 保持单一 sanitization 入口，测试
  覆盖 token/cookie/password/secret 字段和嵌套结构。
- [Risk] policy 配置过宽导致非目标动作被批准 → 只支持精确维度匹配，并拒绝空通配
  或缺字段规则。
- [Risk] 审批后执行长时间未结束 → 使用现有 timeout/hard timeout，并保留已观察的
  trace 摘要以便复盘。
- [Risk] 同 turn 恢复协议不支持当前产品形态 → 将其显式标记为
  `protocol_unverified`，不降级为重放 prompt。
- [Risk] live smoke 产生意外持久副作用 → 只允许 disposable Team，执行前后做
  独立状态断言，并在结束后验证清理完成。

## Migration Plan

1. 未配置 `GENIUS_APPROVAL_POLICY_FILE` 时行为保持不变。
2. 配置仅作用于单次 shim 进程和指定 run/session，进程重启后失效。
3. 回滚时删除该环境变量或策略文件，即可恢复默认拒绝。
4. 若审批协议不兼容，移除 `protocol` 配置并保留默认 deny，不需要回滚 shim 主链路。

## Open Questions

- Genius approval event 的确切字段名、action identifier 和 continuation endpoint
  需要在协议发现阶段核实。
- approval 后的 terminal result 是否复用原 SSE stream、使用 continuation endpoint，
  还是轮询 persisted messages，需要以测试证据确定。
