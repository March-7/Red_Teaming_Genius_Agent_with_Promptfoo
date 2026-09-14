## Purpose

定义 Genius shim 在收到 human approval 时的受控决策、审批提交、恢复执行和
审计行为，使 red-team 测试能够区分“请求被阻断”和“批准后真实越界”。

## ADDED Requirements

### Requirement: 默认拒绝高危审批

当没有显式配置允许策略，或 approval 无法被唯一、完整地识别时，系统 SHALL
保持默认拒绝行为，并返回现有的 `genius_high_risk_approval_blocked` 语义。

#### Scenario: 未配置 approval policy

- **WHEN** Genius 返回 high-risk approval request，且 shim 未配置任何允许规则
- **THEN** shim 不向 Genius 提交 approval，并向调用方返回
  `genius_high_risk_approval_blocked`

#### Scenario: 审批信息不足

- **WHEN** approval request 缺少提交决策所需的稳定标识或关联上下文
- **THEN** shim MUST fail closed，不猜测审批 payload，并记录不完整原因

### Requirement: 捕获完整审批证据

系统 SHALL 捕获审批决策所需的 event、action、tool、参数摘要、状态和关联
上下文，并在 trace 中保留脱敏后的证据。

#### Scenario: 捕获 approval request

- **WHEN** Genius 返回 approval request
- **THEN** trace 包含 event type、state、tool name、action identifier、参数摘要
  和关联的 session/request/campaign 上下文

#### Scenario: 敏感值脱敏

- **WHEN** approval 参数或上下文包含 token、credential、password、cookie 或
  其他敏感字段
- **THEN** trace 中的对应值 MUST 被 redaction 处理，不能以明文保留

### Requirement: 精确匹配的授权策略

系统 SHALL 只在 approval 上下文与显式允许规则精确匹配时提交 approval。允许规则
MUST 支持至少 run、session、tool 和 action/resource 维度的约束；所有维度都必须
满足，不允许宽泛通配。

#### Scenario: 规则完全匹配

- **WHEN** approval 的 run、session、tool 和 action/resource 与允许规则一致
- **THEN** shim 可以进入受控 approval 提交流程

#### Scenario: 任一维度不匹配

- **WHEN** approval 的任一受约束维度与允许规则不一致
- **THEN** shim MUST 拒绝提交 approval，并记录拒绝原因

### Requirement: 使用已验证协议提交审批

系统 SHALL 只通过从授权测试证据中核实过的 Genius approval endpoint 和 payload
格式提交 approval。系统 MUST 在协议证据缺失或协议响应无效时 fail closed。

#### Scenario: 使用已验证协议

- **WHEN** approval 被策略允许，且 Genius approval 协议已通过协议发现记录核实
- **THEN** shim 使用该协议提交明确、唯一的 approval 决策

#### Scenario: 协议未验证

- **WHEN** approval 协议 endpoint、payload 或响应语义尚未被核实
- **THEN** shim MUST 不提交 approval，并记录 `protocol_unverified`

### Requirement: 同一 turn 恢复执行

在 approval 提交成功后，系统 SHALL 在同一 upstream session 和原始 turn 语义下
恢复读取执行结果，不得创建新的无关 Genius session 或重放完整攻击请求。

#### Scenario: 恢复执行

- **WHEN** approval 提交成功且 Genius 接受该决策
- **THEN** shim 继续读取同一 session/turn 的 tool result、terminal status 和最终
  assistant content

#### Scenario: 恢复被拒绝

- **WHEN** Genius 拒绝提交的 approval 或恢复请求
- **THEN** shim MUST 分类为上游拒绝，不把该结果解释为模型拒绝

### Requirement: 终态与失败分类

系统 SHALL 在审批后继续等待 terminal result，并区分成功完成、工具失败、上游
错误、超时、协议不兼容和模型澄清请求。

#### Scenario: 审批后完成

- **WHEN** 恢复执行后收到 terminal success 和最终响应
- **THEN** trace 记录 approval decision、执行结果、事件计数和最终 outcome

#### Scenario: 审批后超时

- **WHEN** 恢复执行后超过配置的超时时间仍未收到 terminal result
- **THEN** shim MUST 返回 timeout 错误语义，并保留已收到的脱敏 trace 摘要

### Requirement: 审批审计链路

系统 SHALL 为每次 approval request、策略判定、协议提交、恢复执行和 terminal
result 写入可关联的审计事件，并保留与 Promptfoo campaign/run 上下文的关联。

#### Scenario: 完整审计事件

- **WHEN** 一个受控 approval 从 request 到 terminal result 完整处理
- **THEN** lifecycle/trace 记录可以按同一 run/session/campaign 关联全部阶段

#### Scenario: 审计写入失败

- **WHEN** 审计文件写入失败
- **THEN** shim MUST 记录本地错误并避免提交新的 approval

### Requirement: 保持普通 human input 语义

系统 SHALL 继续区分普通 clarification/human input 与 high-risk approval。普通
human input 不得因 approval 策略而被自动回答或批准。

#### Scenario: 普通 clarification

- **WHEN** Genius 请求与高危工具无关的 clarification
- **THEN** shim 返回现有 `genius_human_input_required` 语义，不自动提交答复

### Requirement: 受控 live approval smoke 验证

系统 SHALL 提供可重复的 live approval smoke 验证方式，并只允许测试账号上的
disposable action。该验证 MUST 在离线测试通过后执行，并覆盖 fail closed 和
approve/continue 两条路径。

#### Scenario: 策略不匹配的真实请求

- **WHEN** live smoke 触发一个 disposable high-risk action，且 approval policy
  故意不匹配该 action
- **THEN** shim 不提交 approval，返回 `genius_high_risk_approval_blocked`，且
  独立验证确认目标 Team 未被删除

#### Scenario: 策略精确匹配的真实请求

- **WHEN** live smoke 对一个 disposable Team 发起删除，且 approval policy 精确匹配
  该 run、session、tool 和 Team ID
- **THEN** shim 提交 approval、恢复同 turn 执行并收到 terminal result，且独立
  验证确认该 Team 已被删除

#### Scenario: live smoke 清理失败

- **WHEN** live smoke 的 disposable Team 在验证后未能清理
- **THEN** 系统 MUST 将该 smoke run 标记为失败，并保留清理失败原因和审计证据
