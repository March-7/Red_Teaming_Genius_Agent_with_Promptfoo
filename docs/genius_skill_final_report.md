# Genius 平台技能污染评测 —— 整合终报（阶段 0-6）

**日期**：2026-10-28
**评测对象**：Genius 平台技能（skills）生态的 15 个风险家族
**模型矩阵**：Qwen3.8-Max（profile "default"）+ DeepSeek-V4.1-Flash（profile "deepseek-v4.1-flash"），双模型交替
**总预算消耗**：ledger 2,959 / 3,000

## 执行摘要

本次评测以 15 个风险家族 × 100 条样本的规模，对 Genius 平台的技能污染攻击面完成从原生画像到最强攻击形态的完整测量。

**核心发现**：

1. **读操作类攻击面深**：8 个家族可被击穿（0% → 最高 96%），其中两个家族（security-check-bypass、output-reference-poisoning）在权威让渡攻击下接近满分。
2. **写操作与敏感数据是可靠防线**：7 个家族在最强组合拳下仍为 0%。
3. **权威让渡是最强攻击模式**：文档明确指定"以 X 工具为准"，毒化技能成为指定权威后，状态读取类攻击成功率 88-96%。
4. **多源佐证可击穿"事实可核查"轴**：自洽的多源口径（发票+财务公告）使 skill-impersonation 从 0% 升至 27%。
5. **检索是隐藏的断链点**：技能名与模型检索词的匹配度直接影响攻击成败（本轮实测 0% → 100% 的差异）。

## 阶段链条

| 阶段 | 报告 | 内容 |
| --- | --- | --- |
| 0 | `genius_skill_stage0_goal.md` | 评测设计：15 家族、五轴防御模型、oracle 契约 |
| 1 | `genius_skill_stage1_*.md` | 试点：behavior/goal 家族 ASR 测量 |
| 2 | `genius_skill_stage2_*.md` | 三家族推广 |
| 3 | `genius_skill_stage3_*.md` | 全量 15 家族 100 条原生基线 |
| 4 | `genius_skill_stage4_*.md` | 攻击优化迭代（d01-d10 设计变体） |
| 5 | `genius_skill_stage5_*.md` | 两波攻击逻辑试点（w1 让渡/多源 + w2 组合拳） |
| **6** | **`genius_skill_stage6.md`** | **最强形态 100 条收官（本轮）** |

## 最终总表（15 家族 × 100 条最强形态 ASR）

| 家族 | 最强形态 | ASR | 原生 | 提升 |
| --- | --- | --- | --- | --- |
| security-check-bypass | 权威让渡+语境 | **96%** | 0% | +96pp |
| output-reference-poisoning | 权威让渡 | **88%** | 0% | +88pp |
| goal-hijacking | 多源佐证+语境（客户邮件印证） | **63%** | 37% | +26pp |
| safety-bypass | 权威让渡+合规说明 | **46%** | 30% | +16pp |
| skill-impersonation | 多源+算术自洽 | **27%** | 0% | +27pp |
| instruction-override | 让渡+语境（审批工具下发） | **25%** | 10% | +15pp |
| behavior-manipulation | 原生基线 | 35% | 35% | 0 |
| resource-abuse | 原生基线 | 4% | 4% | 0 |
| credential-theft | 原生（真实防线） | 0% | 0% | 0 |
| security-configuration-tampering | 原生（真实防线） | 0% | 0% | 0 |
| malware-delivery | 原生（真实防线） | 0% | 0% | 0 |
| command-parameter-injection | 原生（真实防线） | 0% | 0% | 0 |
| hidden-instruction-evasion | 原生（真实防线） | 0% | 0% | 0 |
| asset-poisoning | 原生（真实防线） | 0% | 0% | 0 |
| content-manipulation | 原生（真实防线） | 0% | 0% | 0 |

机器可读：`runs/final-15-family-strongest-form.json`

## 五轴防御模型（最终验证）

| 轴 | 防御状态 | 击穿方式 |
| --- | --- | --- |
| 事实可核查 | **已击穿（条件性）** | 多源口径自洽（skill-imp 27%）；状态类不可击穿（模型做事实维度归因） |
| 操作风险性 | **最强防线** | 写操作 0% 全家族（7 个写/敏感家族全部挡住） |
| 依赖完备 | 部分击穿 | 递归依赖要求在让渡下被绕过（output-ref 88%） |
| 算术可复核 | 已击破 | 自洽口径使复核失效（20-30%） |
| 来源验证 | **已击破** | 权威让渡直接失效（90-100%） |

## 攻击链五环模型

```
文档让渡权威 → 模型信任让渡 → 技能被发现 → 技能被调用 → 毒值进输出
```

- 断链点 1（检索）：技能名与模型检索词匹配度。修复检索（named 激活）只对读操作有效。
- 断链点 2（安全边界）：敏感数据（凭证）与写操作在此被硬挡。

## 真实防线清单（组合拳后仍 0%，共 7 家族）

1. credential-theft — 敏感数据边界（模型明确拒绝凭证输出）
2. security-configuration-tampering — 变更链写防御
3. malware-delivery — 归档流程防御
4. command-parameter-injection — 命令规范防御
5. hidden-instruction-evasion — 标记规范防御
6. asset-poisoning — 写操作防御（两波验证）
7. content-manipulation — 写操作防御（两波验证）

## 防御建议（按优先级）

1. **权威让渡防护（最高优先）**：技能/文档声明"以 X 为准"时，平台应校验 X 的可信来源链。让渡文档 + 毒化技能的组合目前无任何阻力。
2. **多源一致性校验**：对"口径/公式"类输出，要求模型交叉验证至少两个独立来源，并检测来源是否同源（同一技能族/同一上传批次）。
3. **技能检索透明度**：catalog_search 命中受技能命名影响极大——建议在技能注册时登记领域关键词，减少检索词-技能名的错配（这是攻击者可控制的自由度）。
4. **状态类输出标注**：模型输出"状态/版本/批复"类结论时应附来源标识，允许下游校验。
5. **保持写操作防线**：当前写操作/敏感数据防线表现可靠，建议固化现有的变更单/审批链要求。

## 交付物清单

| 交付物 | 路径 |
| --- | --- |
| 15 家族最强形态总表（机器可读） | `runs/final-15-family-strongest-form.json` |
| 阶段 6 报告 | `docs/genius_skill_stage6.md` |
| 整合终报（本文档） | `docs/genius_skill_final_report.md` |
| 全部阶段报告 | `docs/genius_skill_stage{0-6}*.md` |
| 机器报告 | `runs/stage*-report.json` 等 |
| ledger 记账 | `runs/pilot-standing-ledger.json`（2,959/3,000） |

## 测量质量声明

- evidence_full 100%（630/630 阶段-6 样本）
- 平台清理 0 泄漏（技能/会话全删，核对确认）
- oracle 严格性全程维持（skill_read 自然名 + 毒值 + 无旧值）
- 样本自然业务话术，无 TEST/MOCK/越狱手法
- 预算红线遵守（656/690）
