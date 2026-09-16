## Why

现有 `cross-session-leak` scaffold 仅把 `two_isolated_sessions` 写成 inventory 前置条件；公共 runner 既没有把 Promptfoo 生成的 User A/User B 配对绑定到两个可审计的原生 Genius session，也没有证明 canary 的来源、召回路径和真实授权边界。因此当前 gate 即使显示 `ready`，也不能支持有效的端到端结论。

## What Changes

- 为 `cross-session-leak` 增加受控合成 canary fixture：每个模型/样本使用独立的 source session A 和 attack session B，attack 输入及其可见 metadata 不包含 canary 精确值。
- 将 Promptfoo 的两条生成结果转换为“一次 source seed + 一个正式 attack 结果”，避免把 source turn 混入 20 个正式结果，同时保留原始配对、审查副本和 hash。
- 增加 session-pair registry、持久化消息/trace 关联、本地 exact-match oracle、正向同 session 召回对照和跨 session 负向对照；只有来源、身份/作用域和披露证据同时成立时才允许确认 finding。
- 将 `two_isolated_sessions` 从人工传入标签收紧为可验证的 run-local prerequisite；mock 通过仅证明 runner 结构，不代表真实 Genius 权限隔离。
- 在 manifest 中单列 seed、attack、control 与 generation 调用预算、每模型/样本映射、session 生命周期、共享认证主体和已知/未知的 Project、Team、owner、tenant 边界。
- 明确同一认证账号下的产品级合法跨 session 记忆召回不自动等于越权；不同 Project、不同账号或不同 tenant 不得在缺少第二身份和明确隔离规则时被假设为等价。
- 增加官方说明 brief、离线 preview/gate、mock transport/oracle 测试和准备文档；正式 generation、Genius target、Judge 以及真实最小探针仍分别等待用户明确确认。

## Capabilities

### New Capabilities

无。

### Modified Capabilities

- `genius-plugin-sweep`: 增加 `cross-session-leak` 的受控双 session fixture、可验证前置条件、证据边界、资源生命周期和调用预算要求。

## Impact

- `sweep/briefs.py`、`sweep/scaffold.py`：新增本类别 brief、生成配对归一化、runtime 绑定、manifest、oracle 与 gate 逻辑。
- `shim/genius_service.py`：新增仅限 `cross-session-leak` 的受控 source/attack session 初始化与审计入口；继续使用现有认证与默认 unbound approval policy。
- `tests/test_sweep_scaffold.py`、`tests/test_genius_shim.py`：增加 mock 原生 session、pair isolation、canary 不可见、oracle 与预算测试。
- `sweeps/p1-memory-session-data/cross-session-leak/`、`docs/genius_plugin_sweep.md`、`docs/genius_shim.md`：更新配置、准备说明与运行合同。
- 不新增第三方依赖，不读取或外发真实用户会话/PII，不继承 `pii:api-db` 的 Project 资源或清理授权。
