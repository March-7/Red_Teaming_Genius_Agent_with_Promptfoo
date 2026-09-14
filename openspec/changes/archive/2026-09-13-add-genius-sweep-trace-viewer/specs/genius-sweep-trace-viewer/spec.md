## Purpose

定义 Genius Agent sweep trace viewer 的本地只读浏览、对话时间线、tool call、
approval、oracle、eval 结果和原始 JSONL 检视行为。

## ADDED Requirements

### Requirement: Local-only trace viewer

系统 SHALL 提供一个只读的本地 trace viewer，且 MUST NOT 访问 Genius、
Promptfoo Cloud、任何模型 provider 或任何外部网络服务。

#### Scenario: Viewer startup

- **WHEN** 用户启动 viewer
- **THEN** viewer 只读取本地 trace、lifecycle、eval、oracle 和 summary 文件

#### Scenario: No external network

- **WHEN** viewer 正在运行
- **THEN** 系统 MUST NOT 发起任何 live Genius、模型 provider 或云端请求

### Requirement: Trace source discovery

系统 SHALL 支持从本地目录中发现 trace 数据，包括：

- 当前 `logs/genius_trace.jsonl`
- 当前 `logs/genius_session_lifecycle.jsonl`
- 未来 `sweeps/<group>/<plugin>/runs/<timestamp>/`

#### Scenario: Current global logs

- **WHEN** `logs/genius_trace.jsonl` 和
  `logs/genius_session_lifecycle.jsonl` 存在
- **THEN** viewer 将它们索引为可浏览的 session 和 request 数据

#### Scenario: Future sweep run directory

- **WHEN** `sweeps/<group>/<plugin>/runs/<timestamp>/` 存在
- **THEN** viewer 将该目录索引为一个 run，并关联其中的 trace、lifecycle、
  eval、oracle 和 summary

### Requirement: Conversation timeline

系统 SHALL 将每个 session 的 trace 和 lifecycle 事件重建成一个可浏览的
时间线，并按时间或事件顺序展示。

#### Scenario: Timeline ordering

- **WHEN** 用户打开一个 session
- **THEN** viewer 按事件顺序展示用户消息、assistant 回复、reasoning、tool call、
  approval、错误和 terminal 状态

#### Scenario: Event alignment

- **WHEN** 一个 request 同时具有 trace、lifecycle、oracle 和 eval 结果
- **THEN** viewer 将这些结果对齐到同一个 request 视图中

### Requirement: Conversation-grade presentation

系统 SHALL 将时间线呈现为面向真实 trace 阅读优化的对话式界面，并区分
user、assistant、reasoning、tool call、approval 和 terminal 状态。

#### Scenario: Genius-like transcript

- **WHEN** 用户打开包含对话和 tool call 的 session
- **THEN** user 和 assistant 内容以清晰的对话卡片呈现，reasoning 可折叠，
  tool call 以独立紧凑卡片呈现，并可展开输入和结果

#### Scenario: Approval grouping

- **WHEN** 同一 `confirmation_id` 包含 observed、policy decision、submit、
  continuation 和 terminal result
- **THEN** viewer 将这些事件聚合为可视化的 approval 流程，而不是离散的事件列表

#### Scenario: Long session readability

- **WHEN** 一个 session 包含大量事件
- **THEN** viewer 通过分组、懒加载或虚拟化保持可读性和交互流畅性

### Requirement: Interaction and visual quality

系统 SHALL 提供一致、可导航、可访问的前端交互和视觉状态。

#### Scenario: Event deep link and keyboard navigation

- **WHEN** 用户选择某个事件并复制 URL，或使用键盘在事件之间移动
- **THEN** viewer 恢复或切换到对应事件，并保持可见的选中状态

#### Scenario: Visual states

- **WHEN** viewer 正在加载、没有匹配事件或读取失败
- **THEN** 界面显示对应的加载、空态或错误状态，而不是空白或模糊卡顿

### Requirement: Tool call view

系统 SHALL 为每个 tool call 提供独立卡片，显示：

- `tool_name`
- `tool_input`
- `tool_result`
- `status`
- `request_id`
- `upstream_session_id`

#### Scenario: Tool call card

- **WHEN** 用户打开一个包含 tool call 的 session
- **THEN** viewer 在时间线中显示 tool call 卡片，并允许展开输入和结果

#### Scenario: Tool call filtering

- **WHEN** 用户按 `tool_name` 过滤
- **THEN** viewer 只显示匹配的 tool call 和其所属对话上下文

### Requirement: Approval view

系统 SHALL 为每个 approval 提供独立视图，显示：

- `confirmation_id`
- `action`
- `tool`
- `resource`
- policy decision
- protocol response
- continuation
- terminal result

#### Scenario: Approval timeline

- **WHEN** 用户打开一个包含 approval 的 session
- **THEN** viewer 显示 approval 卡片，并按时间顺序关联 policy decision、
  protocol submit、continuation 和 terminal result

#### Scenario: Approval filtering

- **WHEN** 用户按 `confirmation_id` 或 `outcome` 过滤
- **THEN** viewer 只显示匹配的 approval 及其关联事件

### Requirement: Oracle and eval integration

系统 SHALL 将 oracle 结果和 Promptfoo eval 结果与对应的 request 对齐，并在
详情面板中展示。

#### Scenario: Oracle result

- **WHEN** 一个 request 存在 oracle 结果
- **THEN** viewer 在该 request 详情中显示 oracle 状态和证据引用

#### Scenario: Eval result

- **WHEN** 一个 run 存在 Promptfoo eval 结果
- **THEN** viewer 在该 run 详情中显示样本数、pass/fail、error 和 disposition

### Requirement: Filtering, search and deep links

系统 SHALL 支持按以下维度过滤和搜索：

- `run_id`
- `group_id`
- `plugin_id`
- `upstream_session_id`
- `request_id`
- `outcome`
- `tool_name`
- `confirmation_id`

#### Scenario: Filter

- **WHEN** 用户选择一个或多个过滤条件
- **THEN** viewer 只显示匹配的 run、session、request 和事件

#### Scenario: Search

- **WHEN** 用户输入搜索词
- **THEN** viewer 在事件文本、tool 输入、tool 结果和 metadata 中搜索

#### Scenario: Deep link

- **WHEN** 用户复制或刷新当前视图 URL
- **THEN** viewer 恢复当前选中的 run、session、request、过滤条件和滚动位置

### Requirement: Raw JSONL inspection

系统 SHALL 允许用户展开查看原始 JSONL 行，并保留原始结构。

#### Scenario: Raw event view

- **WHEN** 用户选择一个事件
- **THEN** viewer 显示该事件的原始 JSON，包括完整嵌套结构

#### Scenario: Raw event copy

- **WHEN** 用户复制原始 JSON
- **THEN** 粘贴结果是格式化或可直接解析的 JSON

### Requirement: Security and privacy

系统 SHALL 只绑定 `127.0.0.1`，并 MUST NOT 将本地 trace 数据发送到任何
外部服务。

#### Scenario: Local bind

- **WHEN** viewer 启动
- **THEN** 服务只监听 `127.0.0.1`

#### Scenario: Sensitive data

- **WHEN** trace 中已经包含 redaction 结果
- **THEN** viewer 原样显示 redaction 后的数据，不再尝试还原或解密敏感值
