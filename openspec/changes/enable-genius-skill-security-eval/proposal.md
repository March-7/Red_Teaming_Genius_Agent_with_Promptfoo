## Why

现有 Genius Skill suite 已证明全局助手的 Skill 注册、实际读取、独立状态 oracle 与受控运行设施可用，但原正式计划由单一模型主导生成，100 个组合只覆盖“只读任务中创建会话文件”这一低危害效果面，不能代表有实际危害和样本多样性的 Skills 风险评测。下一阶段改用公开 benchmark 和仓库作为主要风险与样本来源，由 Genius 真实能力、许可与独立 oracle 决定能否进入正式组合。

## What Changes

- 将现有 `skill-task-scope-write` 的 10 Skill × 10 task、C freeze、D3 冒烟和 400 行启动包保留为 calibration 与运行设施证据；旧正式启动包失效，不再接受授权或作为多风险正式统计。
- 建立外部 benchmark 资产 registry，首批审计 AIG/SkillJack、SKILL-INJECT、MalSkillBench 和 SkillsBench；逐资产记录仓库、pinned commit/tag、路径、原始 hash、许可证/使用限制、上游类别、任务、Skill、攻击载体、判据和原环境。
- 采用四级复用：直接复用、最小适配、只复用风险模式、不适用。任何转换都保留原文、转换说明与新 hash，不把上游 mock、LLM Judge、reward 或 scanner 标签当作 Genius ground truth。
- 每个候选先形成风险卡，明确受保护资产、合法任务、信任边界、攻击行为、实际危害、所需 Genius 能力、攻击成功判据、oracle、预设影响上限、结束后残留 disposition 与来源。Normal/positive 只作为历史证据保留，不再是候选资格字段。模型可提名、映射和生成，不能单独决定风险优先级或确认 finding。
- 候选必须通过许可、真实可达性、实质危害、可判定攻击成功、oracle、影响范围预先受限、残留可确认隔离和非重复覆盖 gate。副作用不要求恢复原值；删除、加密、破坏或持久化可以使用本轮自有的一次性合成资源。真实用户资源、未知范围、无法终止的活动或会影响后续 run 的残留仍标为 `not-applicable`/`blocked-prerequisite`。
- 先对完整候选池执行 A/B 双轨筛选并交付轨迹示例，不在筛选阶段新增 target。用户选定正式类别后再决定是否需要小预算 pilot、风险族数量和样本量；正式组合保持多来源与不被单一风险族支配，不继承旧 400 行或 56 行规模。
- 2026-10-05 的十类 pilot、旧四类组合、阶段 E 七类通过结论和两张 package 草案全部保留为旧方法历史证据，不再给任何类别 grandfathered eligibility。所有旧类别与新增来源类别回到 source-complete pool，从原始仓库标签重新映射后并行执行两套筛选：A 为 Genius 上已有明确成功证据的 `observed-success`；B 为来源真实、危害实质、机制忠实且可投递/评分的 `source-faithful-testable`。
- 原 7 风险 × 2 case 的 14-case/56-row breadth bundle 标为 `superseded-for-source-complete-rescreen`。它不得取得正式授权或继续作为第一轮候选；重筛结束后按真正可实施的来源类别重新决定风险族和样本规模。
- 在用户指出当前 14 case 只覆盖 Markdown instruction carrier 后，新增 package Skill capability gate。先验证 Genius 全局助手能否通过可审计 API 导入、读取、测试并实际加载 `SKILL.md + harmless script + asset` 的私有 ZIP package；只有 package lifecycle、脚本调用和资产读取均有独立证据时，才设计 package-script/package-asset 风险并扩充正式 bundle。
- Package runtime 两模型验证后，不再从已验证能力直接选两个风险族。候选池完整收录既有四来源及 MaliciousAgentSkillsBench、SkillLeakBench、SkillFortifyBench、OASB、Under the Hood of SKILL.md、SCR-Bench、SkillLifeBench、HarmfulSkillBench 的全部原始类别、场景标签和正交分类轴；原始标签数量与归一化结果由固定来源内容计算，不预设“21 类”或其他目标数。
- 两套筛选均不设置 normal/positive eligibility gate。A 只按已观察成功事件与有效 oracle 入选，允许暴露低危害或来源适配偏差；B 不要求攻击已经成功，只要求来源威胁真实、危害实质、机制忠实，且在 Genius 上可有效投递并准确评分。两套结果不得合并为一个分数或用 A 替代 B。
- 交付 A∩B、A-only、B-only、neither 四象限及每个保留类别的一条来源→Genius→oracle 轨迹示例。用户审查四象限、来源忠实度与风险真实性后，才决定正式 Target 使用哪些类别和扩充样本数；不得在用户选择前生成新正式 case。
- 用户选择 B 轨全部 23 类后，每类先设计 1 个 source-faithful attack-only case。Case 使用来源语言、与合法功能一致的中性名称加 nonce、真实但有界的同类效果和自然范围限制；除 Skill impersonation 外均按准确名称激活。输出型风险使用预注册 rubric 加人工复核，Judge 如以后授权只作候选。
- 在新 case 上传前，清理账号内所有能由本项目 registry、private owner 和名称读回共同证明归属的历史 Skill；不删除无项目 registry 归属的账号 Skill。清理须逐项 DELETE→GET 404，并从空项目 Skill 集合重新开始。
- 后续 case 必须保留来源样本的 carrier、触发条件、因果链、受保护资产和危害类别。安全替代只能缩小真实影响范围，不能把外传、凭据访问、提权、持久化、依赖劫持或组合授权混淆改成普通本地写文件后继续沿用原风险名称。
- 优先复用公开 benchmark 的合法任务、正常 Skill、攻击语义、任务文件和 verifier；Genius 适配只替换平台接口、合成标识和独立 oracle 所必需的部分。现有本地原创样本仅作为 calibration 或公开来源无法覆盖的 Genius 特有场景。
- 扩展 viewer/source audit，展示 upstream source、risk family、reuse tier、license disposition、adaptation hash、applicability 与 pilot/formal 身份，并保持历史单风险 run 原样可查。

## Capabilities

### New Capabilities

- `genius-skill-security-eval`：公开 benchmark 驱动的 Skill 风险资产 registry、适用性筛选、风险卡、小预算 pilot、多风险组合、真实加载/oracle、统计和重放；同时保留已完成的单风险 calibration 证据。

### Modified Capabilities

- `genius-sweep-trace-viewer`：Skill run 除 suite/risk/case/variant/Skill 身份外，还可按 upstream benchmark、risk family、reuse tier、license/applicability disposition 与 calibration/pilot/formal 阶段过滤和追踪来源。

`genius-plugin-sweep` 与 `genius-controlled-approvals` 的既有 requirements 不变；公共锁、预算、审批、guard、模型和生命周期设施继续复用。

## Impact

- 现有 `skill_suite/`、`skill-suites/`、shim、viewer 和 Promptfoo 适配需要新增外部资产归一化、风险卡、适用性 gate、多风险 portfolio 与来源过滤；旧单风险 schema/run 保持只读兼容。
- 需要对每个公开仓库固定版本并逐资产核对许可证。AIG 根仓库为 Apache-2.0，但 SkillJack README 有 research-only 说明；MalSkillBench 声明 academic research use only；无法确认复用权利的资产只保存元数据/分类，不复制内容。
- SKILL-INJECT 优先提供动态攻击任务与注入结构，SkillsBench 优先提供正常任务、Skill 与 verifier，AIG/SkillJack 和 MalSkillBench 优先提供风险类别、轨迹与恶意载体素材；这些角色是初始策略，最终 disposition 由资产审计决定。
- 当前正式 target/Judge 授权保持关闭。修改规划后，已有单风险正式 bundle 与 4 风险族 `formal-start-bundle-v2` 均不再是可执行的正式计划；阶段 E 使用用户 2026-10-05 的明确授权，将累计 management 上限由 1200 提高到 1440，其余累计上限为 96 target、120 recovery、180 cleanup、0 generation/Judge/retry。正式轮次仍需新的明确授权。
