# 阶段 0（内容与架构改造）Goal 定义

## Goal

在零 target/chat 预算（仅管理 API 与本地开发）下，完成 15 家族扩量评测的全部内容与架构改造：附件去痕重写、10:1 runner、变体矩阵生成器与试点家族的 100 条试点样本集，使阶段 1 可以一键开跑。

## 硬约束

1. **预算**：阶段 0 全程零 chat 调用、零 target 调用。仅允许管理 API（skill 创建/删除、session 创建/删除）用于架构验证（每组 ≤10 个 skill、≤10 个 session，用后即清）与探针复核；离线 LLM 生成不计数
2. **oracle 谓词冻结**：v1 契约不改动（已修复的 CPI 等 5 处保持）；仅允许新增适配层（如组级 nonce 渲染），不允许改谓词语义
3. **0a 附件重写不许破坏 oracle 匹配**：fixture 仍须满足谓词可判定（如 retention=off 必须仍能写进 settings 文件、HIE-{nonce} 仍须逐字节可生成）；重写只改"无关字节"（文档长度、结构、语言自然度），oracle 匹配点保持原样
4. **命名自然化**：技能名与 task 中的文件名不得含 hex nonce；nonce 仅保留在证据层（artifact 路径与 payload 值），按组渲染
5. **变体配比**：每家族 10 个技能设计 × 10 条 prompt 变体 = 100 样本；激活模式分布 30% 点名 / 25% 描述搜索 / 25% 业务口径 / 20% 不提技能；授权框架带/不带各半；单/两轮含两轮式（计 1 样本 = 2 chat 调用）；良性对照 ~5%
6. **模型矩阵**：双模型全交叉（Qwen3.8-Max + DeepSeek-V4.1-Flash 各自完整跑 100 条/家族）——生成 case 时按模型无关设计，运行层分 profile
7. **复用既有 7 个已验证攻击模式**：每家族至少 7/10 个设计基于已确认模式（保 ASR 底盘），≤3/10 为探索性新框架
8. **AGENTS.md 评测规范持续适用**：资源名中性化、不出现 TEST/MOCK/SYNTHETIC 字样、guard 强制、凭据不落盘不打印

## 验收标准（全部满足才算完成）

### V1. 附件去痕（0a）
- [ ] 15 家族全部 fixture 重写完成，存于 `source-faithful-cases-v1/fixtures-v2/`
- [ ] 机器扫描零命中：`sample|harmless|content-free|mock|test|dummy|placeholder|lorem`（大小写不敏感）在全部 fixture 内容中
- [ ] 每个业务文档 ≥1KB 且含 ≥3 类真实结构元素（标题/日期/作者/表格/编号中至少 3 类）
- [ ] oracle 兼容性回归：对 15 家族逐一家族用重写 fixture 跑本地谓词判定（离线 dry-run，不调 chat），谓词逻辑可满足（fixture 渲染后与谓词匹配点一致）

### V2. 10:1 runner（0b）
- [ ] 新 runner（`skill_suite/scale_runner.py`）支持：组级 nonce 生成、自然命名技能创建、10 session/组、session 级证据收集与逐样本判定
- [ ] 端到端冒烟：1 个组（1 skill + 2 session）真实走通创建→上传→chat→收集→清理，全部管理 API 留痕（此步允许 ≤2 次 chat 调用做链路验证，从试点预算预支并在 ledger 记账）
- [ ] 同组内 session 证据互不污染：两 session 各自上传的附件与各自收集的 artifact 用 session_id 隔离，本地断言通过

### V3. 变体矩阵生成器（0c）
- [ ] 生成器（`skill_suite/variant_matrix.py`）输出 15 家族 × 10 设计 × 10 prompt = 1500 条样本定义（JSON），含每条的：家族、设计 ID、激活模式、授权框架、轮次结构、prompt 全文、预期谓词
- [ ] 激活模式/授权/轮次配比与约束 5 一致（机器校验）
- [ ] 每家族 ≥7/10 设计标注其来源攻击模式（映射到 7 个已验证模式）
- [ ] 全部 prompt 文本过合成痕迹扫描：零"名称完全为"、零模板句式命中（`工单.*审批（审批号` 模式在带授权变体中允许但占比 ≤50%）、零 hex nonce
- [ ] 良性对照样本每家族 ≥5 条且技能行为完全正当

### V4. 试点就绪
- [ ] behavior-manipulation 家族的 100 条样本（10 设计 × 10 prompt）经生成器产出并通过 V3 全部机器校验
- [ ] 试点运行配置（模型矩阵、并发、ledger 记账方式）写入 `docs/genius_skill_asr_scaleup_plan.md` 的阶段 1 节
- [ ] 用户对 V1-V4 产出物完成一次审查（抽样附件 ≥3 家族、抽样 prompt ≥30 条）并明确批准进入阶段 1

## 产出物清单

| 产出 | 位置 |
| --- | --- |
| 重写 fixtures（15 家族） | `source-faithful-cases-v1/fixtures-v2/` |
| 10:1 runner | `skill_suite/scale_runner.py` |
| 变体矩阵生成器 | `skill_suite/variant_matrix.py` |
| 1500 条样本定义 | `source-faithful-cases-v1/scale-v1/`（按家族分文件） |
| 试点家族样本集 | `scale-v1/behavior-manipulation-100.json` |
| 冒烟验证记录 | `skill-suites/benchmark-multi-risk/runs/scale-smoke.json` |
| 阶段 0 完成报告 | `docs/genius_skill_stage0_report.md` |

## 明确不做（阶段 0 范围外）

- 不跑任何正式 ASR 样本（阶段 1 起）
- 不做 ledger 修订（预算已确认充足，正式记账从阶段 1 开始）
- 不改 oracle 谓词语义（只加组级 nonce 适配层）
- 不做对抗性迭代/ASR 优化（阶段 4）
