
## Context

当前仓库已经具备：

- Genius OpenAI-compatible shim
- 受控 approval policy
- `POST /chat/stream` approval 协议
- 同 turn continuation
- trace / lifecycle 审计
- Promptfoo 0.122.2

这些能力足以支撑逐插件 sweep，但当前还没有统一的目录结构、inventory、
prerequisite gate、run manifest 和 deterministic summary 生成方式。

## Goals / Non-Goals

**Goals:**

- 建立可复现的 sweep 目录结构
- 建立确定的 39-plugin inventory
- 建立每个 plugin 的独立 policy 绑定
- 建立统一的 run artifact 和 summary 结构
- 建立插件级 prerequisite gate
- 建立首个 plugin 的端到端样板
- 保持 group 级暂停

**Non-Goals:**

- 不执行完整 39-plugin sweep
- 不引入自定义 `policy` / `intent` plugin
- 不修改 Genius shim 的审批协议
- 不修改 Promptfoo provider 或 OpenAI-compatible target 协议

## Decisions

### 1. 目录结构

采用物理隔离，而不是把所有 plugin 放在同一个配置文件里：

```text
sweeps/
  inventory.json
  p0-agent-control/
    hijacking/
      config.basic.yaml
      approval-policy.json
      runs/
        2026-09-12T12-00-00/
          generated.basic.yaml
          eval.json
          eval.jsonl
          genius_trace.jsonl
          session_lifecycle.jsonl
          oracle.jsonl
          run-manifest.json
          summary.md
      summary.md
```

原因：

- 每个 plugin 的配置、policy 和运行结果独立
- 便于逐插件暂停、复盘和归档
- 便于后续按 group 生成 summary
- 降低配置漂移和误删风险

**备选方案**：使用单一 `promptfooconfig.yaml` 加多个 plugin。该方案更容易
一次性误扫全部 plugin，不利于逐插件审计。

### 2. Inventory 结构

使用 `sweeps/inventory.json` 保存：

```json
{
  "groups": [
    {
      "id": "p0-agent-control",
      "priority": 0,
      "plugins": [
        {
          "id": "hijacking",
          "prerequisites": [],
          "status": "ready"
        }
      ]
    }
  ]
}
```

每个 plugin 记录：

- `id`
- `prerequisites`
- `status`
- `group`

状态只允许：

- `ready`
- `blocked-prerequisite`
- `not-applicable`
- `candidate`
- `no-finding-in-small-sample`
- `target-error`

### 3. Policy 绑定

每个 plugin 使用独立的 `approval-policy.json`，只包含当前 plugin 的精确
allow 规则。所有字段必须显式填写：

- `run_id`
- `session_id`
- `tool`
- `action_id`
- `resource`

不允许通配、缺字段或跨 plugin 共享。

原因：

- 避免一次 policy 误授权其他 plugin
- 便于按 plugin 审计
- 与 `genius-controlled-approvals` 的精确匹配语义一致

### 4. Prerequisite gate

在执行 plugin 前检查：

- 是否需要额外 role
- 是否需要隔离 object
- 是否需要 RAG 文档
- 是否需要 MCP / shell / SQL 能力
- 是否需要多轮 session
- 是否需要外部网络

如果条件不满足，plugin 被标记为 `blocked-prerequisite` 或
`not-applicable`，不会进入 baseline run。

**备选方案**：直接执行所有 plugin。该方案会产生大量无效 pass，误导结果。

### 5. Run manifest

每个 run 目录包含 `run-manifest.json`，记录：

- `run_id`
- `group_id`
- `plugin_id`
- `strategy`
- `git_commit`
- `promptfoo_version`
- `python_version`
- `config_hash`
- `policy_hash`
- `started_at`
- `finished_at`
- `status`

目的：

- 让每次 run 可复现
- 支持后续回归和审计
- 避免只依赖目录名推断语义

### 6. Deterministic summary

新增一个 summary generator，不使用 LLM 生成结论。

输入：

- `generated.basic.yaml`
- `eval.json`
- `genius_trace.jsonl`
- `session_lifecycle.jsonl`
- `oracle.jsonl`
- `run-manifest.json`

输出：

- `summary.md`
- 可选的 `summary.json`

分类：

- `confirmed-boundary-violation`
- `suspected-boundary-violation`
- `attempted-but-blocked`
- `approved-no-effect`
- `expected-authorized-effect`
- `invalid-generation`
- `target-error`
- `blocked-prerequisite`
- `not-applicable`
- `cleanup-failed`
- `no-finding-in-small-sample`

### 7. 首个样板 plugin

选择 `p0-agent-control/hijacking` 作为首个样板，原因：

- 不依赖额外 role、RAG、MCP 或外部网络
- 与 Genius Agent 的核心行为直接相关
- 可以最快验证目录、policy、run 和 summary 是否闭环

### 8. Group 暂停

每个 group 完成后必须暂停并生成 group summary。用户确认后才进入下一个
group。

原因：

- 避免一次性消耗大量请求
- 便于在每个 group 后修正 inventory 或 policy
- 保留人工审查点

## Risks / Trade-offs

- [Risk] 目录结构较重，39 个 plugin 会产生大量小文件 → 通过脚本生成和维护，
  并将 raw run 产物 Git ignore
- [Risk] inventory 与 Promptfoo plugin 版本漂移 → 在 manifest 中记录
  Promptfoo 版本，并在测试中校验 plugin ID 是否存在
- [Risk] policy 绑定过严导致 live run 被拒绝 → 这是预期行为；fail closed
  优先于误授权
- [Risk] summary generator 变成新的逻辑复杂点 → 只做确定性聚合，不做结论推断
- [Risk] 首个样板 plugin 不能代表所有 plugin 的执行方式 → 该 change 只建立
  骨架，不承诺完整 sweep 覆盖

## Migration Plan

1. 生成 `sweeps/` 目录和 `inventory.json`
2. 生成 39 个 plugin 子目录
3. 为首个 plugin 生成 `config.basic.yaml` 和 `approval-policy.json`
4. 实现 run manifest 和 summary generator
5. 用首个 plugin 做一次离线结构验证
6. 暂停，不自动进入完整 sweep

## Resolved Decisions

首个样板 plugin 固定为 `hijacking`。它不依赖额外 role、RAG、MCP 或外部
网络，能最快验证目录、配置、policy、run 和 summary 的闭环。
