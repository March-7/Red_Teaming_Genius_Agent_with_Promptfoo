# Genius Skill campaign：100 组合的离线合同

实现：`skill_suite/campaign.py`。A/B 的小预算生命周期仍使用原 suite schema；campaign 单独表示 **10 个不同攻击 Skill × 每个独立设计 10 个合法任务**。目前真实生成尚未开始，仓库中的合同测试仅在临时目录创建 fixture。

## 本地入口

```bash
npm run skill:campaign:validate -- --plan <source-dir>/campaign-plan.json
npm run skill:campaign:preview -- --plan <source-dir>/campaign-plan.json
npm run skill:campaign:dry-run -- --plan <source-dir>/campaign-plan.json
npm run skill:campaign:review-template -- --plan <source-dir>/campaign-plan.json
npm run skill:campaign:validate -- --plan <source-dir>/campaign-plan.json --review <source-dir>/campaign-review.json
npm run skill:campaign:freeze -- --plan <source-dir>/campaign-plan.json --review <source-dir>/campaign-review.json --output <new-sibling-dir>
npm run skill:campaign:verify -- --output <frozen-dir>
npm run skill:formal:capacity -- --plan <source-dir>/campaign-plan.json
npm run skill:formal:config-draft -- --plan <source-dir>/campaign-plan.json --output <new-file>
npm run skill:formal:judge-plan -- --plan <source-dir>/campaign-plan.json --formal-config <draft.yaml> --output <new-dir>
npm run skill:d:plan -- --plan <source-dir>/campaign-plan.json --case-id <reviewed-id> --output <new-dir> --run-id <neutral-id>
```

命令不读取 `.env`，不初始化 provider，不调用网络。dry-run 输出确定性的 400 行：每模型 100 attack + 100 normal，总计 200 attack + 200 normal。行中只有 logical scope/session key，`native_resources=null`；不伪造已创建的 Genius 资源。当前会话文件风险使用 schema v3：每条只读 user task 恰好使用 `{resource_name}`，不得出现目标文件名或 `{record_id}`；目标文件名只在攻击 Skill 和本地 oracle 中。旧 v1/v2 双 locator 合同仅供历史包读取。模型/variant 的可变 scope、session 与 locator 各自独立，pair 内任务模板与初始状态 hash 相同；渲染后的任务 hash 与 locator 映射分别记录。

## `campaign-plan.json`

顶层严格字段：`schema_version=3`、`target_context=global-general`、`kind=skill-campaign`、`campaign_id`、一个 `risk_id`、`risk_contract`、固定 `model_matrix`、`execution`、`generation`、`skills`。未知字段被拒绝。

- `risk_contract`：`boundary`、`allowed_behavior`、`failure_criterion`、`oracle_type`、`effect_surface`。当前效果面固定为 `native-general-session-artifact-creation`，写入风险限定 `request-read-only` / `independent-state-readback`。
- `model_matrix`：复用 `sweep/models.py` 两模型，显式 high/on；后端实际设置未由请求证明。
- `execution`：concurrency 2、retry 0、retain、expected_target_calls 400。
- `skills`：恰好 10 项，每项有 `skill_key`、固定 `effect_artifact_name`、normal/attack 两份完整文本的 artifact ref，以及 10 个 tasks。攻击正文必须各不相同，且与对应正常正文不同；目标名只出现在攻击正文。
- 每个 task：`task_id`、`user_task_template`、`template_sha256`、`allowed_behavior`、`failure_criterion`、`attack_goal`、`initial_state` ref。每个 Skill 的 10 个任务模板不能重复；不同 Skill 可共享一条通用基线提问，但 100 个 Skill–任务组合编号必须唯一，并在逐条语义审查中记录文字重复情况。初始状态必须是非空 JSON object；具体字段及独立 oracle 在实际风险验收时确认。
- artifact ref：`{"file":"source-relative-path","sha256":"full-hash"}`，指向实际字节，禁止绝对路径、越界路径、`..` alias 与 hash 漂移。

生成配置独立包含 origin、provider_id、model、max_requests、每请求 max_input_tokens/max_output_tokens、concurrency 2、retry 0、发送字段、provider_config 和 receipt ref。preview 展示 provider、HTTPS API destination、预算和数据流。token 上限是配置预算，实际 tokenizer/usage 计量仍须真实 generator 实现；本合同不把计划预算当作实测 token 数。

provider_config 只保存 provider_id、model、api_base_url、credential_env **变量名**和 temperature setting，不允许 resolved key。发送字段限定为合成的 `risk_contract`、`skill_template`、`legitimate_task_requirements`；目标凭据、真实 trace 和 run 产物不得发送。具体值仍需用户审查该阶段 provider 与数据流后授权；offline 校验不证明内容的真实合成来源。

## 来源与逐条审查

`generation.origin=offline-fixture` 可以用于 validate/preview/dry-run，但 receipt 不能声称 online call 或 human authorization，freeze 始终拒绝。`provider-response` 要求明确 hosted provider、C-generation 的人类开始记录和范围 hash、顺序编号的请求/响应 refs，预算内完整覆盖 10 Skill/100 task。schema v3 保存 Promptfoo 实际收到的每 job prompt、原始 HTTP response、独占 attempt receipt、生成 YAML、normalized payload 和落盘 Skill/task 字节，逐层校验身份与 hash。结构正确的本地文件本身不证明网络调用发生；fixture 仅验证管线合同。

v3 freeze 还复制固定文件名引用的 generation plan/authorization/result/ledger，以及每个 job 的 plugin、live config 与 prompt 原文。`verify` 从复制后的 source 重建完整生成→Skill/task 链；缺任一文件或 prompt hash 漂移均失败。单元测试中可构造外观为 provider-response 的伪回执来检验这些校验器，但只有实际在线 provider attempt 才能支撑真实生成结论。

`campaign-review.json` 顶层 actor 必须为 `codex-semantic-review`，不是 `human-reviewer`。每条记录必须有 case id、task/normal/attack/state/criterion hash、accept、带 timezone 的时间，并逐项说明七个检查的理由：合法任务、payload 仅在 Skill、pair 任务一致、初始状态等价、独立 oracle、合成数据、中性名称。review-template 的初值全部 pending/false，不能自动接受。缺一条、重复、无理由、未解决或 hash 漂移都不能冻结。这里的 Codex 语义审查不代替正式结果中的人工漏洞确认。

## 冻结包与正式就绪

freeze 只能另存到源目录外的新目录，保留源字节，传递复制请求、响应、原始生成与 artifact refs，重新校验复制后的内容。输出：

- `source/campaign-plan.json`、`source/campaign-review.json` 和所有源材料。
- `formal-matrix.jsonl`：预期 400 行，未创建 native resources、未提交 target。
- `review-index.md`：100 条审查总索引，保留完整 hash。
- `campaign-freeze.json`：整个 artifact inventory/hash、计数与零实际调用；verify 重建来源、审查和矩阵，拒绝内容、manifest 或 inventory 漂移。

所有上述输出固定 `formal_ready=false`。真实 A、B、D、可审计 API provisioner 和正式配置/容量预算仍是独立必要证据。正式运行授权另行确认，本长期 goal 停在正式轮次之前。

当前新 freeze 使用显式 v3 global-general。400 行全部固定 general；资源容器 locator 不改变 target 路由。历史 v1/v2 可离线读取，不能替代当前会话文件风险的 v3 保密边界。

`skill:formal:capacity` 仅从已校验的 v3 计划推导 400 行按需创建的资源与已知 API 步骤；fixture 可运行，但输出始终是 `offline-draft`、`formal_ready=false`，未知管理开销与 Judge/recovery 上限保留为空。它不代替真实 API 容量 pilot、正式配置或开始授权。

`skill:formal:config-draft` 只导出 opaque selection 的 400 行 Promptfoo 预览：200 正常行本地 JSON 断言，200 攻击行候选 rubric；target 始终为 offline-only file provider，guard 固定挂载。默认 Judge 为阻断 provider；`--judge-mode one-shot` 仅接受通过 `verify_frozen` 的 provider-response 来源，改为一次性 Judge 候选，但仍无授权且不能提交正式 target。伪 provider-response 冻结包的离线集成测试已验证配置与 200 行 Judge 计划可衔接；该伪来源不构成真实生成证据。

`skill:formal:judge-plan` 仅准备 200 条攻击行的一次性 Judge 候选与未授权记录；fixture 来源可测试格式，真实 provider-response 来源必须先有通过 `verify_frozen` 的完整冻结包。准备成功不会启用正式评分。

## 公开 benchmark 多风险入口

旧 10 Skill × 10 task campaign 保留为 calibration。新的多风险准备使用以下离线入口：

```bash
npm run skill:benchmark:validate -- --registry <source-registry> --inventory <inventory> --summary <inventory-summary>
npm run skill:benchmark:relationships:validate -- --registry <source-registry> --inventory <inventory> --summary <inventory-summary> --output <relationships-dir>
npm run skill:risk-cards:validate -- --index <risk-card-index> --capabilities <capability-registry> --sources <source-registry> --relationships <relationship-summary> --project-root . --shortlist <risk-shortlist>
npm run skill:pilot-cases:validate -- --index <pilot-index> --project-root . --shortlist <risk-shortlist> --card-index <risk-card-index> --capabilities <capability-registry> --sources <source-registry> --inventory <inventory> --inventory-summary <inventory-summary> --relationships <relationship-summary>
npm run skill:pilot:results -- validate --base skill-suites/benchmark-multi-risk --shortlist <risk-shortlist> --output <pilot-summary>
```

首轮 10 个候选为 0/10；四类中间修订为 4/4。阶段 E 随后完成全部十类前置验证，最终 7 类有效、3 类 blocked，累计 72 target、945 management、7 recovery、58 cleanup、0 generation/Judge/retry。旧 `formal-cases-v2`、`formal-plan-v2.json` 和 `formal-start-bundle-v2` 已 supersede。Breadth v1 已离线生成 7 风险 × 每族 2 case = 14 case、56 行；来源 SkillsBench 7、MalSkillBench 4、AIG/SkillJack 3，状态 `ready-for-user-case-review`，target/Judge 仍为 0。
