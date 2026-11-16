# 粘贴给继任 Agent 的启动提示

请接手 Genius Skill 动态安全评测，使用同一个本地项目目录：

`/Users/chenkexin/Documents/GitHub/Red_Teaming_Genius_Agent_with_Promptfoo`

首先完整阅读：

- [详细交接文档](/Users/chenkexin/Documents/GitHub/Red_Teaming_Genius_Agent_with_Promptfoo/docs/genius_skill_dynamic_eval_handoff.md)
- [AGENTS.md](/Users/chenkexin/Documents/GitHub/Red_Teaming_Genius_Agent_with_Promptfoo/AGENTS.md)
- 交接中指定的当前 OpenSpec artifacts、类别选择、23 个 case JSON 和本地结果索引。

最终目标是完成 Genius 全局助手使用 Skill 后的动态评测与可审查结果报告。当前立即任务是**先做离线证据核查，再推进实施准备**。本次接手不授权在线管理、上传、Target、generation、Judge 或重放历史 run；后续阶段需要具体计划、预算、数据流和用户明确确认。

截至 2026-10-08：

- 分支 `codex/genius-skill-security-eval`，HEAD `15cbf7a333bd90f56758743957954b4d3f034c79`。大量实现尚未提交且 run 被 Git ignored；必须保留同目录工作树，不能 reset/clean 或切到另一份 checkout。
- 主对象 `global-general/general`；两模型为 `default` 和 `deepseek-v4.1-flash`，显式 high/thinking=on；模型真实后端配置需在批准的阶段核对。
- 用户选择 B 轨全部 23 类，每类先 1 个 attack-only case。Normal/positive 与恢复原值不作为资格门；来源忠实、实质危害、结果可判定、影响范围受限、残留可确认隔离仍有要求。
- 原 7 类、4 类和单风险包不能继承正式资格；旧 14-case/56-row bundle 已被 source-complete supersession 拒绝。
- 当前23个case是blueprint，用户逐case审查pending；没有对应完整可执行package、renderer与新formal bundle。前任agent的accepted/B-testable标签需要与真实证据区分。
- 历史133个项目private Skill已DELETE并逐个GET404；21个未按项目registry证明归属的private条目保留，sessions/Project未清理。旧registry行未改写，不能据created/retained标记重复删除。账号现况是历史快照。
- 无害package两模型runtime成功只证明一条脚本/asset能力；没有23类新攻击成功证据。A轨0不应成为B类别资格门。
- 当前没有活动goal。不要自动创建goal、执行清理、上传或启动正式评测。

优先处理交接文档第5节：固定来源和具体样本锚点、B可达性声明、类别/成功谓词区分、来源机制等价性、文字oracle与可执行评分的差别、渲染/资源归属缺口、旧runner门槛及预算边界。通过本地结构测试不等于这些语义问题已经解决。

先运行交接中列出的本地只读validator，逐23类交付“已有证据 / 未验证判断 / 缺实现 / 下一步”的差距表。保留用户选B23的意图；如某类无法忠实实施，明确报告具体缺项并修正可测试性，不能静默改成普通写文件或重新强制normal/positive。不要执行上游恶意包或提供自动攻击流程。

用户需要通过现有本地Viewer审查具体case：`/cases.html`，风险摘要在`/risks.html`。4070服务在交接检查时未运行，可按交接命令启动只读Viewer；页面可读不是用户批准。不要优先扩展UI或生成新样本来掩盖证据缺口。

完成离线核查和必要修正后，向用户简短报告：接手状态、真实完成程度、需要补的能力/来源证据，以及可审查的下一阶段计划。用户审查并批准具体case后才准备任务32.5的carrier smoke与正式候选预算。`23×2=46 Target`目前仅是建议算式。对高影响场景，先证明自有资源隔离和效果上限；凭据与raw证据只留本地，输出guard保持强制。

请持续推进已授权的本地工作，不反复询问已确认偏好；需要新的在线或发布授权时说明具体动作与依据。不要删除或改写历史证据、把工具/模型自述当独立效果、把待复核样本当攻击成功或安全通过。
