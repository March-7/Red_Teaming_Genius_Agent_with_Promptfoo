## Why

当前 `enable-controlled-genius-approvals` 已完成并归档，shim 已经能在受控条件下提交 Genius approval 并继续同 turn 执行。为了开始大规模 red-team sweep，需要一个可复现、可审计、可逐插件暂停的 sweep 骨架，而不是把 39 个 plugin 混在一次扫描里。

## What Changes

- 新增 `sweeps/` 目录结构，按 priority group 和 plugin 物理隔离配置、policy、运行记录和 summary。
- 建立内置 plugin inventory，覆盖 6 个优先级组和 39 个 Promptfoo plugin。
- 为每个 plugin 建立独立目录：
  - `config.basic.yaml`
  - `approval-policy.json`
  - `runs/`
  - `summary.md`
- 建立统一的 run manifest、trace/lifecycle 归档、oracle 结果和 deterministic summary 生成规则。
- 建立每个 plugin 的 prerequisite gate，区分：
  - `ready`
  - `blocked-prerequisite`
  - `not-applicable`
- 建立首个 plugin 的端到端样板，验证目录、配置、policy、运行和 summary 能闭环。
- 不在本 change 中执行完整 39-plugin sweep，也不引入自定义 `policy` / `intent` plugin。

## Capabilities

### New Capabilities

- `genius-plugin-sweep`: 定义 Genius Agent 上 Promptfoo plugin sweep 的目录结构、inventory、运行产物、policy 绑定、prerequisite gate、summary 生成和插件级执行语义。

### Modified Capabilities

无。本 change 只新增 sweep 骨架，不修改 `genius-controlled-approvals` 的既有行为。

## Impact

- 新增 `sweeps/` 目录和 39 个 plugin 子目录。
- 新增 sweep inventory、run manifest、summary 生成脚本和示例配置。
- 可能新增少量测试或文档，用于验证目录结构和 summary 生成。
- 不修改 Genius shim 的审批行为。
- 不修改 Promptfoo provider 或 OpenAI-compatible target 协议。
