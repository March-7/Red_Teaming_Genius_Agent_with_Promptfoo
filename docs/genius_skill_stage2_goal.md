# 阶段 2（3 家族方法论推广）Goal 定义

## Goal

在 3 个家族（behavior-manipulation 复测 + content-manipulation + hidden-instruction-evasion）上完成方法论推广验证：每家族 100 条 ASR 测量（共 300 条），带完整证据捕获（evidence_mode=full），产出 3 家族对比 ASR 报告，并验证阶段 1 的关键发现是否跨家族成立（轻量暗示 > 重型框架、口语授权提升 ASR、良性对照污染现象）。

## 家族选择理由

| 家族 | 角色 | 已知基线 |
| --- | --- | --- |
| behavior-manipulation | 复测（完整证据版） | 阶段 1: 43% ASR，d08 轻量暗示 80% |
| content-manipulation | 授权依赖型 | 探测期确认依赖预授权模式——验证授权框架效应 |
| hidden-instruction-evasion | 标记型（artifact 谓词） | 探测期确认依赖中性标记（HIE）——验证不同谓词类型下的 ASR |

## 运行参数

| 项 | 值 |
| --- | --- |
| 总量 | 300 样本（3 家族 × 100） |
| 分组 | 30 组（每家族 10 组 × 1 skill + 10 session） |
| chat 预算 | ≤340 次（300 主调用 + 15 两轮铺垫 + 25 容差）；超出立即停止 |
| 证据模式 | **full**（完整 answer/thinking/tool_trace 落盘后才删 session） |
| 模型 | 双模型全交叉（每家族 Qwen/DeepSeek 各 ~50） |
| 执行顺序 | 家族串行（一个家族 10 组跑完再下一个），组内串行 |
| 失败处理 | 单条记 invalid 不重试；预算耗尽停止并出报告（已跑部分照常分析） |
| 清理 | 每组结束即清（安全删除模式）；证据先于清理落盘 |

## 硬约束

1. **预算**：≤340 次 chat。ledger 已修订至 3000（用户批准），每家族记账
2. **跑完不优化**：300 条全部跑完前不做任何变体改写（即使某家族中途 ASR 为 0）
3. **谓词/样本冻结**：用阶段 0 生成的 `scale-v1/*-100.json` 原样，不改判定
4. **证据完整性**：每条 result JSON 含 evidence_full（完整 answer + thinking + tool_trace）；任何 evidence_full 缺失视为执行缺陷需补查
5. **零重试**：单条失败不重发；整组失败（skill 409 等）跳组记录
6. **guard 强制、凭据安全、资源名中性**（AGENTS.md 规范）

## 验收标准

### V1. 执行完成
- [ ] 3 家族各 ≤100 条执行完毕（或预算停止点），每条有 result JSON（status/predicates/evidence_full/session_id）
- [ ] evidence_full 完整率 100%（无缺失）
- [ ] 清理凭证：30 skill + 300 session 删除（或残留清单+清理）

### V2. 三家族 ASR 报告
- [ ] 每家族：总 ASR + 模型/激活/授权/设计切分（同阶段 1 格式）
- [ ] **跨家族对比表**：三家族并排（模式 × 家族 ASR 矩阵）
- [ ] 阶段 1 发现的复验：
  - 轻量暗示（探索设计）vs 重型框架的 ASR 差异是否跨家族成立
  - 授权框架效应（with vs without）三家族对比
  - 良性对照污染（技能加载影响非任务交互）是否再现
- [ ] 拒绝样本 evaluation awareness 残留检查（零命中目标）
- [ ] invalid 清单与原因

### V3. 阶段 3 就绪判定
- [ ] 方法论结论：轻量暗示优势是否足够稳定（≥2/3 家族成立）可作为阶段 3 的设计权重依据
- [ ] 产出阶段 3 全量计划修订建议（15 家族 × 100，含预算估算）
- [ ] 报告落盘 + 用户通知

## 产出物

| 产出 | 位置 |
| --- | --- |
| 30 个组 run 目录（含逐条 result + evidence_full） | `scale-runs/s2-*` 或 `group-*` |
| 三家族 ASR 报告 | `docs/genius_skill_stage2_three_family_asr.md` |
| 机器可读版 | `runs/stage2-three-family-asr.json` |
| ledger 记账 | 每家族一条 amendment |

## 明确不做

- 不跑剩余 12 家族（阶段 3，需再确认）
- 不做对抗性改写（阶段 4）
- 不改样本定义/谓词
- behavior-manipulation 复测不与阶段 1 结果合并统计（分立报告，对比呈现）
