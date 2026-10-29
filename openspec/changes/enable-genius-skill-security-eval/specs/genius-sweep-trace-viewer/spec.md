## ADDED Requirements

### Requirement: 主研究入口与历史 Workspace 记录可区分

Viewer SHALL 展示 Skill run 的 target context 与实际 session_type；新主研究为 global-general，旧 Workspace run 保持原身份、单独展示。无显式 target context 的旧 run MUST 标为历史/入口未锁定，不能默认升级为 general 就绪证据。

#### Scenario: 打开旧 Workspace A

- **WHEN** 打开已停止的 Workspace A run
- **THEN** 保留其 workspace 路由与 source-unverified，不合并主研究阶段覆盖或统计

### Requirement: A/B 双轨风险轨迹审查页

Viewer SHALL 提供独立的人类审查页，从冻结的 category catalogue、family map、dual-gate screening 与 trajectory artifacts 动态读取数据，不复制第二套手写结论。

#### Scenario: 浏览 B-only 轨迹

- **WHEN** 用户打开本地风险轨迹页面
- **THEN** 页面显示来源数、原始条目、family、A/B 四象限计数，并默认列出 23 个 B-only 类别
- **AND** 用户可搜索、按象限和来源筛选；选择类别后展示具体来源锚点、carrier→trigger→action→sink→effect、Genius 适配路径、成功 oracle、fidelity delta、影响上限、残留 disposition 与缺失证据

#### Scenario: 本地只读与响应式边界

- **WHEN** 页面在桌面或移动视口加载
- **THEN** 所有数据只通过同源只读 API 提供，页面不发起外部请求、不执行 payload、不修改评测 artifact，URL 可恢复选中 family 和筛选条件
- **AND** 小屏幕不得产生横向页面溢出，API 缺失时显示可理解的空状态

### Requirement: 23 个 source-faithful Case 审查页

Viewer SHALL 提供独立 Case 审查页，直接读取冻结的 `source-faithful-cases-v1`，不把 Markdown 摘要作为数据源。

#### Scenario: 逐条浏览 Case

- **WHEN** 用户打开 Case 审查页
- **THEN** 页面默认列出 23 个 case，并可按 carrier、来源和关键词筛选；URL 可恢复选中 case
- **AND** 详情展示普通 user request、Skill 名称与行为、来源五步链、成功与 invalid/unresolved 判据、证据、真实风险类比、影响上限、资源 disposition 和来源锚点

#### Scenario: Case 页面保持离线只读

- **WHEN** 浏览桌面或移动页面
- **THEN** API 只返回 blueprint，payload status 必须为 `blueprint-no-executable-payload`，Target/generation/Judge 计数均为 0
- **AND** 页面不发外部请求、不修改 case artifact，小屏幕无横向页面溢出

## MODIFIED Requirements

### Requirement: Trace source discovery

系统 SHALL 支持从本地目录中发现 trace 数据，包括：

- 当前 `logs/genius_trace.jsonl`
- 当前 `logs/genius_session_lifecycle.jsonl`
- 未来 `sweeps/<group>/<plugin>/runs/<timestamp>/`
- 独立 `skill-suites/<risk-id>/runs/<run-id>/`

#### Scenario: Current global logs

- **WHEN** `logs/genius_trace.jsonl` 和
  `logs/genius_session_lifecycle.jsonl` 存在
- **THEN** viewer 将它们索引为可浏览的 session 和 request 数据

#### Scenario: Future sweep run directory

- **WHEN** `sweeps/<group>/<plugin>/runs/<timestamp>/` 存在
- **THEN** viewer 将该目录索引为一个 run，并关联其中的 trace、lifecycle、
  eval、oracle 和 summary

#### Scenario: Skill suite run directory

- **WHEN** `skill-suites/<risk-id>/runs/<run-id>/` 存在
- **THEN** viewer 将其索引为独立 Skill suite run，显示 manifest 中的 suite/risk 身份，并关联 Skill registry、source audit、trace、lifecycle、状态 oracle、存在时的 eval 和 summary
- **AND** 以明确的 case/model/variant、session/turn/tool id 关联证据，不按行号或顺序猜测归属；缺失关联显示为 unlinked，不修改原产物

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
- Skill run 的 `suite_id`、`risk_id`、`case_id`、`variant`、`skill_id`、`skill_version` 和 `skill_hash`
- benchmark 派生 run 的 `source_id`、`upstream_repo`、`upstream_asset_id`、`risk_family`、`reuse_tier`、`license_disposition`、`applicability` 和 `evaluation_stage`

#### Scenario: Filter

- **WHEN** 用户选择一个或多个过滤条件
- **THEN** viewer 只显示匹配的 run、session、request 和事件

#### Scenario: Search

- **WHEN** 用户输入搜索词
- **THEN** viewer 在事件文本、tool 输入、tool 结果和 metadata 中搜索

#### Scenario: Deep link

- **WHEN** 用户复制或刷新当前视图 URL
- **THEN** viewer 恢复当前选中的 run、session、request、过滤条件和滚动位置

#### Scenario: Skill pair navigation

- **WHEN** 用户按 case 和 variant 查看正常/攻击配对
- **THEN** viewer 显示相应 Skill 身份与 hash、合法任务、加载覆盖、工具/服务事件及 before/after oracle，并能跳转对应本地证据
- **AND** 生命周期 run 没有 eval 时展示 `Judge: not-run`，不据此推断 PASS；旧来源没有 Skill 字段时仍正常浏览

#### Scenario: 外部 benchmark 来源追踪

- **WHEN** 用户打开或筛选外部 benchmark 派生的 calibration、pilot 或 formal case
- **THEN** viewer 展示 pinned source、原始/适配 hash、风险族、复用等级、许可证与适用性 disposition，并能跳转本地 source audit/risk card/oracle
- **AND** 只有 taxonomy/metadata 的候选不得显示成已导入 Skill 或动态 Genius finding；旧本地原创 run 继续正常浏览并标记 `local-original`
