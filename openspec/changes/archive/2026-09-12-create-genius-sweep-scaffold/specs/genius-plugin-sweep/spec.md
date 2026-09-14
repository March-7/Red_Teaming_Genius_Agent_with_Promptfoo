## Purpose

定义 Genius Agent 上 Promptfoo plugin sweep 的目录结构、inventory、运行产物、
policy 绑定、prerequisite gate、summary 生成和插件级执行语义。

## ADDED Requirements

### Requirement: Sweep inventory and directory layout

系统 SHALL 提供一个确定的 sweep inventory，覆盖 6 个 priority group 和 39 个
Promptfoo built-in plugin，并为每个 plugin 建立独立目录。

#### Scenario: Inventory completeness

- **WHEN** 读取 sweep inventory
- **THEN** 系统返回 6 个 group 和 39 个唯一 plugin，且每个 plugin 只属于一个 group

#### Scenario: Plugin directory layout

- **WHEN** 检查任意 plugin 目录
- **THEN** 该目录包含 `config.basic.yaml`、`approval-policy.json`、`runs/` 和
  `summary.md`

### Requirement: Plugin-specific policy binding

系统 SHALL 为每个 plugin 提供独立的 approval policy 绑定，且所有 policy 都必须
使用精确匹配，不允许通配。

#### Scenario: Exact policy binding

- **WHEN** 读取某个 plugin 的 `approval-policy.json`
- **THEN** policy 中的 `run_id`、`session_id`、`tool`、`action_id` 和
  `resource` 都是唯一确定的值

#### Scenario: Missing policy

- **WHEN** 某个 plugin 缺少 `approval-policy.json` 或 policy 内容无效
- **THEN** 该 plugin 的 run MUST fail closed，不得提交 approval

### Requirement: Prerequisite gate

系统 SHALL 在执行每个 plugin 之前检查该 plugin 的前提条件，并只允许
`ready` 的 plugin 进入 baseline run。

#### Scenario: Prerequisite satisfied

- **WHEN** plugin 的 prerequisite 检查全部通过
- **THEN** 该 plugin 被标记为 `ready`，可以进入 baseline run

#### Scenario: Prerequisite missing

- **WHEN** plugin 缺少必要的 session、role、object、RAG、MCP、shell 或 SQL 条件
- **THEN** 该 plugin MUST 被标记为 `blocked-prerequisite` 或 `not-applicable`，
  不得伪装成已测试

### Requirement: Run artifact contract

系统 SHALL 为每次 plugin run 创建一个独立的时间戳目录，并保存可复现和可审计的
运行产物。

#### Scenario: Complete run artifacts

- **WHEN** 一次 plugin run 完成
- **THEN** run 目录包含 `generated.basic.yaml`、`eval.json`、
  `genius_trace.jsonl`、`session_lifecycle.jsonl`、`oracle.jsonl`、
  `run-manifest.json` 和 `summary.md`

#### Scenario: Raw output isolation

- **WHEN** 检查 Git 状态
- **THEN** 原始 run 产物 MUST 被 Git ignore，只有配置和脱敏 summary 可以提交

### Requirement: Deterministic summary generation

系统 SHALL 从 run artifacts 确定性生成 plugin summary，不得依赖 LLM 生成结论。

#### Scenario: Summary from artifacts

- **WHEN** `generated.basic.yaml`、`eval.json`、`genius_trace.jsonl`、
  `session_lifecycle.jsonl` 和 `oracle.jsonl` 都存在
- **THEN** 系统生成 `summary.md`，其中包含 run、plugin、policy、样本数、
  disposition 和证据引用

#### Scenario: Missing artifact

- **WHEN** 任一必要 run artifact 缺失
- **THEN** summary MUST 标记 `incomplete`，并指出缺失的 artifact

### Requirement: Plugin execution semantics

系统 SHALL 按插件逐个执行 baseline run，每个 plugin 先执行 2 条 `basic` 用例，
再根据结果决定是否升级。

#### Scenario: Baseline run

- **WHEN** plugin 进入 baseline run
- **THEN** 系统执行 2 条 `basic` 用例，并把结果写入该 plugin 的 run 目录

#### Scenario: Escalation decision

- **WHEN** baseline 中存在有效失败样本
- **THEN** 该 plugin MUST 被标记为 `candidate`，并停止进一步升级

#### Scenario: Baseline all pass

- **WHEN** 2 条 baseline 用例都通过且没有 target error
- **THEN** 该 plugin 才允许进入后续攻击策略

### Requirement: Group-level pause

系统 SHALL 在每个 priority group 完成后暂停，不得自动进入下一个 group。

#### Scenario: Group completed

- **WHEN** 一个 group 内所有 plugin 都完成或被标记为 blocked / not-applicable
- **THEN** 系统生成 group summary 并暂停，等待用户确认后才继续

#### Scenario: Automatic continuation

- **WHEN** 没有用户确认
- **THEN** 系统 MUST NOT 自动开始下一个 group

### Requirement: Built-in plugin only

系统 SHALL 只使用 Promptfoo built-in plugin，不引入自定义 `policy` 或
`intent` plugin。

#### Scenario: Custom plugin rejected

- **WHEN** sweep inventory 中出现自定义 `policy` 或 `intent` plugin
- **THEN** 系统拒绝该 inventory 并报告错误
