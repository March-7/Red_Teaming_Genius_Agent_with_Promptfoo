# hijacking 双模型 basic 汇总

- 旧结果：2026-09-14 按用户要求删除，不再纳入统计。
- 新实验状态：`blocked-applicability`；2026-09-14 已获重跑授权，阻塞原因不是缺少开始许可。
- 模型：Qwen3.8-Max / high 与 DeepSeek-V4-Flash / high。
- 样本：同组 10 条 basic 输入，两模型各 10 次，共 20 次；总并发 2。
- 生成样本：0；正式评测：0；本次未调用生成器、target 或 Judge。
- ASR：未定义，不报告 0%，不记为通过。
- 适用性：已重新阅读官方判据并复核当前 purpose，仍无经核实的排他性业务用途限制。

## 适用性复核

官方文档：https://www.promptfoo.dev/docs/red-team/plugins/hijacking/

官方测试前提是有明确用途范围的助手，观察它是否被引导完成范围外工作。当前 Genius
purpose 仍明确包含通用问答、数据分析、Skills 和 Projects/Teams；未补充可核实的
受限入口、角色或产品规则。科研背景不能推出旅游、娱乐等话题被禁止。双模型配对和
high 请求配置不改变这一前提，因此不能凭正常通用问答构造攻击成功判据。

详见 [用途边界复核](../../../docs/genius_scope_assessment.md)。这次判断基于当前配置和
已有画像，未重新访谈在线部署，也不使用已删除的旧测试结果。

## 配置与实际执行

| Target label | model_profile | reasoning_effort / thinking 请求 | 计划次数 | 实际次数 | 有效样本 | ASR |
| --- | --- | --- | --- | --- | --- | --- |
| Qwen3.8-Max / high | default | high / on | 10 | 0 | 0 | 未定义 |
| DeepSeek-V4-Flash / high | deepseek-v4-flash | high / on | 10 | 0 | 0 | 未定义 |

上述是配置请求参数，后端实际档位为 `request-only/unverified`，不是本类别运行证明。
因为未执行，不存在本轮 target/grader 错误、评分待复核样本或攻击成功候选；适用性
阻塞单独记录，不构造 20 条错误样本。没有新 run manifest 或原始评测产物。

本次验证：`npm run sweep:preview -- --plugin hijacking` 离线成功，确认同组 10 条
basic 输入、两模型共 20 次、生成/eval 总并发 2。默认 unbound policy 保持不变。

后续只有真实用途限制和失败判据成立后才可执行。届时沿用已有重跑授权，按主线串行
交接，在 excessive-agency 完成后通过 `npm run sweep:run` 和全项目锁运行；当前不
占用执行队列、不生成输入，不需要用户重复确认开始。
