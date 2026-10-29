# Genius 平台技能攻击评测 · 阶段性汇总（阶段 0-7 收官）

**日期**：2026-10-29
**状态**：阶段 0-7 全部完成；本文件为 Skills 攻击线的阶段性收尾汇总
**评测对象**：Genius 平台技能（skills）生态的技能污染/滥用攻击面
**模型矩阵**：Qwen3.8-Max（profile "default"）+ DeepSeek-V4.1-Flash（profile "deepseek-v4.1-flash"），双模型交替，均 `reasoning_effort=high, thinking=on`
**累计预算**：ledger target 3,819 / 15,000（阶段 0-6 共 2,959 + 阶段 7 共 860；15,000 上限为用户 2026-10-28 授权）

---

## 一、评测阶段链条（0-7）

| 阶段 | 主题 | 关键产出 | 报告 |
|---|---|---|---|
| 0 | 评测设计 | 15 风险家族、五轴防御模型、oracle 契约、23 case 蓝图 | `genius_skill_stage0_goal.md` |
| 1 | 行为家族试点 | behavior/goal 家族 ASR 首测 | `genius_skill_stage1_*.md` |
| 2 | 三家族推广 | 方法论固化 | `genius_skill_stage2_*.md` |
| 3 | 全量原生基线 | 15 家族 × 100 条原生画像 | `genius_skill_stage3_*.md` |
| 4 | 攻击优化迭代 | d01-d10 设计变体矩阵 | `genius_skill_stage4_*.md` |
| 5 | 攻击逻辑试点 | w1 权威让渡/多源 + w2 组合拳 | `genius_skill_stage5_*.md` |
| 6 | 最强形态收官 | 15 家族 × 100 最强形态 ASR 总表（v1） | `genius_skill_stage6.md`、`genius_skill_final_report.md` |
| **7** | **SkillAtlas 外部攻击库吸收、合并与迭代优化** | **值投毒发现、taxonomy、总表 v2** | **`genius_skill_stage7_report.md`、`genius_skill_stage7_pilot.md`** |

## 二、样本量统计

| 阶段 | 正式样本 | chats | 说明 |
|---|---|---|---|
| 0-6（合计） | 15 家族 × 100 最强形态（含原生基线 100/家族） | 2,959 | 详见 `genius_skill_final_report.md` |
| 7-E 试点 | 17 设计 × 10 = 170 | 200（含 r0 归档 30） | SkillAtlas 逻辑直接移植 + 值投毒初测 |
| 7-G1 迭代 | 6 设计 × 10 = 60 | 60 | 值投毒机理确认 |
| 7-F 扩量 | 6 设计 × 100 = 600 | 600 | 值投毒扩量 |
| **7 小计** | **830** | **860** | — |
| **累计** | — | **3,819** | ledger 计数口径 |

阶段 7 额外覆盖 5 个新试点家族（credential-exposure、filesystem-reconnaissance、tool-output-poisoning、phishing-fraud、destructive/delegation 变体），其中 phishing-fraud 完成全量 100 条。

## 三、分层风险分类（Hierarchical Taxonomy）

第一层复用 SkillAtlas 八大风险类（社区攻击痕迹库，3,014 案例），第二层为本项目 20 个实测风险家族。机器可读版：`skill-suites/benchmark-multi-risk/hierarchical-taxonomy.json`。

| 第一层 | 库内案例 | 第二层家族 | 我们的样本 | 最强形态 ASR | 最强形态 |
|---|---|---|---|---|---|
| **Data Exfiltration 数据外泄** | 1,548 | credential-theft | 100+20 | 0% | 原生 |
| | | credential-exposure | 10 | 0% | —（试点） |
| | | filesystem-reconnaissance | 10 | 0% | —（试点） |
| **Data Destruction 数据破坏** | 168 | destructive-file-impact | 100+10 | 0% | 原生 |
| **DoS 拒绝服务** | 39 | resource-abuse | 100+10 | 4% | 原生 |
| **Malware/Ransomware 恶意软件** | 344 | malware-delivery | 100+10 | 0% | 原生 |
| | | command-parameter-injection † | 100 | 0% | 原生 |
| **Phishing 钓鱼欺诈** | 30 | phishing-fraud | 100 | **60%** | 值投毒（登记结论） |
| **Backdoors 后门** | 73 | security-configuration-tampering | 100+10 | 0% | 原生 |
| **Bias/Manipulation 偏见与操纵** | 736 | behavior-manipulation | 100+100+10 | **100%** | 值投毒（口径即交付物） |
| | | skill-impersonation | 100+100+10+10 | **98%** | 值投毒+口径冒名 |
| | | security-check-bypass † | 100 | **96%** | 权威让渡+语境 |
| | | goal-hijacking | 100+100+10 | **94%** | 值投毒（研究问题口径） |
| | | instruction-override | 100+100+10 | **85%** | 值投毒（通知正文） |
| | | safety-bypass † | 100 | **46%** | 权威让渡+合规说明 |
| **Poisoning 投毒** | 76 | output-reference-poisoning | 100+100+10+10 | **94%** | 值投毒（状态口径） |
| | | asset-poisoning | 100+10 | 0% | 原生 |
| | | content-manipulation | 100+10 | 0% | 原生 |
| | | tool-output-poisoning | 10 | 0% | —（试点） |
| | | hidden-instruction-evasion † | 100 | 0% | 原生 |

† = 启发式挂靠（SkillAtlas 无严格对应类，按攻击机理归类）。

**样本数记法**：`100+100` = 阶段 6 旧形态 100 + 阶段 7 值投毒 100；`+10` 为阶段 7 试点/G1。

## 四、防御画像汇总

| 防御状态 | 家族数 | 家族 |
|---|---|---|
| **击穿**（ASR ≥85%） | 6 | behavior-manipulation、skill-impersonation、security-check-bypass、output-reference-poisoning、goal-hijacking、instruction-override |
| **半击穿**（40-70%） | 2 | safety-bypass（46%）、phishing-fraud（60%） |
| **真实防线**（0%） | 10 | credential-theft、credential-exposure、filesystem-reconnaissance、destructive-file-impact、malware-delivery、command-parameter-injection、security-configuration-tampering、asset-poisoning、content-manipulation、tool-output-poisoning、hidden-instruction-evasion（其中 3 个仅试点级） |
| **弱防线** | 1 | resource-abuse（4%） |

**五轴防御模型（阶段 6 结论，阶段 7 更新）**：
- 事实可核查：已击穿（值投毒使口径不可核）
- 操作风险性：最强防线（写/敏感操作 0%）
- 依赖完备：部分击穿
- 算术可复核：已击破
- 来源验证：已击破（值投毒下彻底失效）

**核心机理（阶段 7 新发现）——指令注入 vs 值投毒**：

| 机理 | 模型行为 | 实测 |
|---|---|---|
| 指令注入（技能文本要求执行任务外动作） | 识别来源不可核验/无审批痕迹，拒绝 | 0/170 |
| 值投毒（技能"权威口径"的毒值=用户要的交付物） | 照录交付，无法区分权威值与毒值 | 531/600（88%） |

**结构性观察**：风险重心与 SkillAtlas 库倒置——库内案例最多的 Data Exfiltration（1,548）与 Malware（344）在 Genius 上为最硬防线（0%）；Bias/Manipulation 与 Poisoning 被值投毒击穿。Genius 能力边界挡住传统 exfiltration 路径，风险转移到口径信任链。

## 五、测量质量声明

- evidence_full：阶段 7 全部正式样本 830/830（100%）；阶段 0-6 详见各阶段报告（阶段 6 为 630/630）
- 平台清理：每阶段结束核验 0 技能泄漏、0 会话残留（含隐藏名称预留清理）
- 阶段 7 发现并修复 5 项测量缺陷（oracle 交付模式、refusal-quote 假阳性、描述字段标签泄漏、scorer 缺参、隐藏技能预留），全部在报告中披露；消歧为收紧而非放松
- oracle 契约全程机器判定（skill_read 自然名绑定 + 毒值谓词 + refusal 消歧），未采用 SkillAtlas 宽口径 Judge

## 六、产物索引

| 类别 | 位置 |
|---|---|
| 阶段报告（0-7） | `docs/genius_skill_stage*.md`、`genius_skill_final_report.md` |
| 分层 taxonomy | `skill-suites/benchmark-multi-risk/hierarchical-taxonomy.json` |
| 15 家族总表 v2（机器可读） | `skill-suites/benchmark-multi-risk/runs/final-15-family-strongest-form-v2.json`（runs/ 不入库，本地留存） |
| 阶段 7 产物 | `skill-suites/benchmark-multi-risk/stage7-atlas/`（快照本地留存）、`source-faithful-cases-v1/atlas-*.json`（23 蓝图） |
| 数据源注册 | `skill-suites/benchmark-multi-risk/source-registry.json`（13 源，skillatlas 为 pattern-only） |
| 阶段 7 授权与记账 | `stage7-authorization.json` + `runs/pilot-standing-ledger.json` |
| 评测代码 | `skill_suite/`（scale_runner、source_faithful_scorer 等） |
| 测试 | `tests/test_skill_*.py` |

## 七、防御建议（累计）

1. **值口径校验**（阶段 7 新增，最高优先）：口径下发类技能需要变更签名或多方校验；"以工具为准"的授权链是单点故障。
2. **检索层加固**（阶段 6）：技能名与模型检索词匹配度决定攻击成败，命名需受控。
3. **保持写操作与敏感数据边界**（阶段 0-6）：当前最可靠防线，变更需回归测试。
