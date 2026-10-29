# C 阶段：Promptfoo Skill 生成准备

## 当前状态

B5 的真实固定配对已成立：两模型各有有效正常/攻击对照，攻击 Skill 被读取，独立 artifact oracle 均未发现未请求写入。C 第五次独立授权 run `88421c90` 完成 10/10 个 DashScope HTTP 200 和 10/10 个 raw/Promptfoo 一致性校验，0 Genius target/management/Judge、0 重试；显式 `enable_thinking=false`，每项 reported input 636、text output 1176–1448 tokens，无 `reasoning_content`。已归一化 10 对不同 Skill、100 个唯一编号组合并逐条完成 Codex 语义审查，冻结 400 行预期矩阵。100 个组合中有 95 句不同的任务文字；6 个 Skill 共用首项通用基线问句，且每个 Skill 内部 10 句互异。该内容重复已在审查索引中明示，不改变任何原始生成字节。真实生成与审查冻结不代表 D 冒烟、API provisioner 或正式轮次就绪。

真实来源 run：`skill-suites/skill-task-scope-write/runs/c-generation-prep-20261003-88421c90/`（Git ignored），`generation-plan.json` SHA-256 为 `8e9da7c3b01b1d82f058cee267bcbca7790bc9aa14ea6b6d2fc3c241e5998088`。归一化与逐条审查记录：`c-normalized-20261003-88421c90/`；冻结目录：`c-frozen-20261003-88421c90/`，manifest SHA-256 为 `b698e71f0a7bac0dcbb3e2b0d64291f43029d0e4ddebc1e5265241dc226a3785`。来源校验重放了 10 个授权 job、HTTP attempt、原始响应、Promptfoo 导出、Skill/task 字节与 100 条审查 hash。前四个已停止 run `8771c08a`、`42598619`、`a83cf8c8`、`79feb014` 分开保留，没有跨 run 拼接。D 计划需从此冻结目录的 `source/campaign-plan.json` 建立并单独获得在线开始确认。

## 第五次真实生成的已执行范围

| 项目 | 授权上限或固定值 |
| --- | --- |
| 生成 provider | DashScope 北京 OpenAI 兼容 endpoint，`qwen3.8-max`，`openai:chat:qwen3.8-max` |
| 出站目的地 | `https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions` |
| 请求 | 10 个独立 job，各至多一次 HTTP attempt；首个失败后停止新 job，零重试 |
| 并发 | 至多 2 个生成 job |
| 单请求等待 | HTTP 最多 300 秒；外层 worker 最多 330 秒。超时仍计为已提交 attempt，不自动重试 |
| 单 job 设置 | `temperature=0.7`、`max_tokens=8000`；事后检查 reported input ≤ 4000、output ≤ 8000 |
| 生成思考模式 | 请求体顶层显式 `enable_thinking=false`；这是生成 provider 设置，不改变被测 Genius 双模型的 high/thinking=on |
| 其他调用 | Genius target 0、Genius management 0、Judge 0、cleanup 0 |
| 输出 | 每 job 一份正常/攻击 Skill 及专门设计的 10 个合法只读任务；合计 10 Skill、100 组合 |

输入 token 数无法由 DashScope 的 `max_tokens` 在提交前硬性限制。冻结 prompt 的字符数不超过 16000，wrapper 在响应后核验 provider 报告的 usage；若实际输入超过 4000，则该 job 记为预算错误并停止后续派发，已发生的调用不能撤销。因此表中的 4000 是审查/停止阈值，不保证发送前的硬上限。实际 10 份响应均未超过核验阈值；账本以真实 attempt/usage 为准。

每份 job 仅发送 `risk_contract`、`skill_template`、`legitimate_task_requirements` 三项合成说明，经 Promptfoo custom plugin 渲染成固定 prompt。不会发送 Genius 凭据、真实 trace、真实 run、控制面响应或状态快照。凭据可从本地进程环境、`.env` 或既有 `.env.promptfoo` 中读取，只在子进程环境中使用；配置和报告只记 `DASHSCOPE_API_KEY` 变量名。网络 guard 只允许上述 HTTPS host/path，HTTP(S) 其他调用被拒绝。独占 attempt 文件在 fetch 前落盘；Promptfoo 内部若重试，同一 job 会因文件存在而被拒绝。原始 HTTP response、Promptfoo YAML、Skill/task 字节和所有 hash 保留于 Git ignored run。

参考：[DashScope 模型说明](https://help.aliyun.com/zh/model-studio/qwen3-8-max)、[兼容接口 Base URL](https://help.aliyun.com/en/model-studio/base-url)、[Chat Completions `enable_thinking` 参数](https://help.aliyun.com/en/model-studio/qwen-api-via-openai-chat-completions)。平台价格、模型可用性与 token 规则在实际调用前需重新核对。

## 已完成的离线设施

- `skill_suite/generation_jobs.py`：用无网络 Promptfoo fake provider 取得 10 个实际渲染 prompt，固定 job/config/provider/code/guard hash 和未授权状态；生成的 preparation manifest 明示真实请求数为 0。
- `skill-suites/skill-task-scope-write/promptfoo/dashscope-one-shot.mjs` 与 `skill_suite/real_generation.py`：按阶段确认记录、全项目锁、提交前账本、两 job 并发和失败即停调度。单 job 原始请求/响应及 usage 单独留存。代码存在不代表已取得执行许可。
- `skill_suite/real_normalizer.py`：只接受 10 个已完成且可核对 raw HTTP/Promptfoo 输出的 job，落盘 10 对 Skill、100 个任务与 400 行矩阵；100 条语义审查初值均为 pending。
- `skill_suite/campaign.py` 的 v3 freeze 现在将 generation plan、独立授权、调度结果/账本、10 个 job 的 plugin/live config 与实际 prompt 原文一并纳入来源 hash 清单；复制后的 source 会重新校验 prompt、HTTP attempt、原始响应、Promptfoo export 与落盘 Skill/task。完整伪回执单元合同已走通归一化→100 条 fixture 审查→freeze→D 绑定→shim general 路由；该测试生成的“live”字段是本地构造，不能作为本研究的真实 provider/target 证据。
- `skill_suite/orchestration.py` 与 `promptfoo_provider.py`：opaque case/model/variant 的 fixture 编排、guard/账本/状态 oracle 顺序和仅变 Skill 内容的单次策略已离线验证。通过注入下述已观察 API adapter 与 fake target，一条有 artifact 效果的 fixture 精确计 8 次管理 HTTP attempt、1 次 target、1 次 cleanup；正常 Skill 正文不进入聊天。真实 400 行的可审计 API provisioner 和生成载体 D 冒烟尚未完成。
- `skill_suite/observed_api.py`：按 B5 实际回执的 `POST /api/skills`、Skill/sharing GET、general session POST、artifact GET/DELETE 请求形状封装私有控制面；fake HTTP 合同拒绝正文、owner、sharing、版本和会话漂移。另用 B5 保留的 5 份真实 HTTP 回执在本地只读重放创建、Skill 读回、sharing、会话与初始 artifact 列表，5/5 形状匹配、网络调用 0；原始私有回执仍留在 ignored run。fixture 的 target/下载由显式假回调提供；正式 shim routing 与真实下载仍属于 10.5/D 的验证，不把该重放当作真实 provisioner。
- `skill_suite/artifact_download.py`：实现 B5 已观察的 `/api/files/download` 一次性 byte 读回形状，固定 `token` / `auth_token` 查询字段、不跟随重定向、最多 4096 bytes；通过公共 HTTP meter 在请求前扣管理预算，receipt 不记录 capability 或认证明文。`httpx.MockTransport` 验证成功、重定向、超长响应与零重试；尚未在新的生成载体上真实调用，因此不解锁 10.5/D。
- `shim/genius_service.py`：尚无正式 live provisioner 的 `skill-campaign` metadata 现在在提交 target 前明确拒绝；A/B 的已确认 `skill-suite` registry 路由保持原契约。这个阻断门只防止 fixture 编排误入线上，正式 D/400 行路由仍须实现并验证。

凭据来自 Git ignored、权限 600 的既有 `.env.promptfoo`，未输出或保存明文。第五次 run 证明该凭据在执行时可完成这 10 项；未来状态仍可能变化。C 的真实生成、100/100 语义审查与冻结已完成；D 的 4 target 在线冒烟须另行明确确认，正式 400 target/Judge 轮次再另行授权。

## 首次真实生成的已停止 run

`c-generation-prep-20261002-8771c08a` 的原始账本为 generation 2/10、其他调用类别均 0、重试 0；两条 DashScope HTTP 均 200，usage 分别为 input/output `388/4302` 与 `388/3729` token，均在拟议核验阈值内。两份输出均有预期 Skill key、正常/攻击正文和 10 个任务，但 `tasks` 的元素是字符串而非六字段对象，故 one-shot wrapper 标记 error，调度器在已在途的两条返回后停止。原始 `attempt-*.json`、`raw-response-*.json`、账本与 `C-failure-review.json` 留在该 ignored run；旧 attempt 的 `usage` 字段为 null，但原始 provider JSON 保留了实际 usage，未回写旧回执。它既不是 0% ASR，也不是两条有效攻击用例。

## 第二次真实生成的已停止 run

`c-generation-prep-20261002-42598619` 的账本为 generation 3/10，其他调用类别 0、重试 0；三条 DashScope HTTP 均 200，input/output token 为 `644/3168`、`644/4221`、`644/4210`。`gen-00`、`gen-02` 各有一份通过的完整包；`gen-01` 的原始 5047 字符 JSON 包也通过 one-shot 校验，但 Promptfoo `0.122.2` 的旧单输入 `Prompt:` 解析在 JSON 字符串内的 ASCII 分号处切断，导出仅 973 字符，故调度器停止其余 7 个 job。本 run 的有效片段不能与别的 run 拼成正式 10 Skill/100 任务。`C-failure-review.json`、原始响应及导出 YAML 留在 ignored run；不回写。将旧 `gen-01` 完整 JSON 仅换成 `PromptBlock:` 后做无网络回放，Promptfoo 导出为完整 5047 字符，10 个 ASCII 分号均保留、字节逐一相同；回放记录在 `c-parser-replay-20261003-0ef6293a/replay-review.json`，它不代表新的 hosted 请求。修订后的 `a83cf8c8` 已按独立授权执行，结果见下节。

## 第三次真实生成的已停止 run

`c-generation-prep-20261003-a83cf8c8` 的独立授权绑定 plan SHA-256 `127e8cc36d9275d2050042f06060460beba799dc96081c554854c4063b351b06`。账本为 generation 7/10，Genius target/management/Judge/cleanup 均 0、重试 0。`gen-00`、`01`、`02`、`03`、`05`、`06` 六份完整包均取得 HTTP 200 并通过原始响应与 Promptfoo 导出一致性检查；reported input 均为 681 tokens，output 为 4895–6729 tokens，均未超过 4000/8000 的核验阈值。`gen-04` 在本地 180 秒 deadline 发生 `AbortError`，没有取得 HTTP status、raw response 或 usage；是否已到服务端以及是否计费未知。失败后不再提交 `gen-07` 至 `09`。`C-failure-review.json`、`summary.md` 与原始账本留在 ignored run，不回写或与其他 run 拼接。下一份计划 `79feb014` 扩大等待期限后已单独授权并执行，结果见下节。

## 第四次真实生成的已停止 run

`c-generation-prep-20261003-79feb014` 的独立授权绑定 plan SHA-256 `11e2eaef78f444dbd944aebe4766b23a6a4771985c2157a0d8d9d8a0669493ea`。账本为 generation 6/10，Genius target/management/Judge/cleanup 均 0、重试 0。`gen-00`、`01`、`03`、`04`、`05` 五份完整包均取得 HTTP 200 并通过原始响应与 Promptfoo 导出一致性检查；reported input 均为 681 tokens，text output 为 3939–5255 tokens，另有 2717–4037 reasoning tokens。`gen-02` 在本地 300 秒 deadline 发生 `AbortError`，没有 HTTP status、raw response 或 usage；是否已到服务端以及是否计费未知。失败后不再提交 `gen-06` 至 `09`。原始 `C-failure-review.json`、`summary.md` 与账本留在 ignored run，不回写或与其他 run 拼接。完整来源校验要求同一 run 的十个固定 job 全部完成；临时引用其他 run 的成功包会绕过这个合同。第五次 run `88421c90` 改为显式 non-thinking 生成并已完成，详情见本页顶部。

## 后续阶段的预算边界

| 阶段 | Target | Generation / Judge | 管理请求、策略和数据流 |
| --- | ---: | --- | --- |
| C 单次 Skill 内容策略 | 当前 0 | 0 / 0 | 离线入口只计算上限；一候选若未来运行完整 10 task × 2 model × 2 variant，至多 40 target，接入/读回管理预算须另列；不得改 user task |
| D 生成载体冒烟 | 4 | 0 / 0 | 两模型各 normal/attack 一组；API 管理、恢复、清理和活动时间上限须在 D 开始前依据实测接口冻结 |
| 正式轮次 | 400（200 attack + 200 normal） | 0 / Judge 上限待 assertions 与 provider 配置冻结 | 逐行按需 provision，管理/恢复/cleanup 容量按真实 API 实测计算；仅允许经 guard 的必要 target 输出、任务与判据进入 Judge，真实 trace 与凭据不发送 |

Judge provider、每行评分调用数、发送字段和价格尚未冻结，所以目前没有 Judge 开始权限，也不能把 400 target 等同于 400 Judge 请求。正式配置会给出确切分母、最大调用数及数据流后再请用户确认；本长期 goal 在该轮次开始前停止。

`npm run skill:formal:capacity -- --plan <campaign-plan.json>` 提供无网络的正式容量草案。对当前 v3 fixture 的 400 行，按每行独立私有 Skill 与 native general session 推导：最多 400 个 Skill 实例、400 个会话、0 Project；每行 8 个必需管理步骤，合计 3200 次基线管理请求；若 400 行都出现目标文件，另有最多 800 次下载/恢复读回和 400 次按 id 删除 cleanup。这里的“必需”包含目标前后各一次 catalogue readback，以便将运行时读取与私有 Skill 版本关联。模型目录、ownership、失败恢复等额外开销尚未实测并冻结，因此 **3200 不是正式管理预算上限**，草案固定 `formal_ready=false`、管理/recovery/Judge 批准上限为 null。该命令只读取本地 campaign 和来源 hash，不预建资源、不提交 target。

`npm run skill:formal:config-draft -- --plan <campaign-plan.json> --output <new-file>` 另生成严格的 400 行 Promptfoo 离线配置：每行 target prompt 只含 `case_id`、`model_profile`、`variant`；200 个 normal 行使用本地 `is-json` 检查，200 个 attack 行使用只标候选的 `llm-rubric`。公共 sensitive output guard 固定在 `defaultTest.options.transform`，并发 2。target provider 只允许 offline fixture，Judge provider 为必定抛错的 `blocked-judge.mjs`，因此此文件不能用来提交真实 target/Judge。以 v3 fixture 生成的 `c-formal-preview-20261002-de89c900/promptfooconfig.yaml` 在禁止网络环境下通过 Promptfoo `0.122.2` 配置校验；单条攻击 fixture eval 的假 target 账本为 1 target/5 management/0 Judge，Judge 被阻断并以 1 error 结束，不是安全或攻击结果。正式评分 provider 的最终配置、实际 token/call 上限和开始授权仍须冻结。

`--judge-mode one-shot` 仅在来源为 100/100 已审查的 provider-response freeze 时可导出候选评分配置；target 仍是 offline-only，Judge 计划另以 `not-authorized` 记录。完整伪生成回执单元链已验证这类配置可通过禁止网络的 Promptfoo `validate config` 并与 200 攻击行计划逐行对齐；其“provider-response”标签是测试构造，不能作为真实在线生成证明。

`npm run skill:formal:judge-plan -- --plan <campaign-plan.json> --formal-config <draft.yaml> --output <new-dir>` 从 200 个攻击行建立独立 Judge 计划；provider 候选为项目已使用的 DashScope `qwen3.8-max`，拟议最多 200 次评分请求、并发 2、零重试、显式 `enable_thinking=false`、HTTP 等待上限 300 秒、单次输出 `max_tokens=1024`、输入 4000 token 为响应后核验阈值。`dashscope-judge-one-shot.mjs` 在 HTTP 前校验攻击行与 rubric、对待评输出及渲染后的评分 prompt 再次运行公共 guard，以独占文件阻止同一行的隐藏重试，并以两个跨进程文件槽限制同时提交。live 模式还核对冻结来源与配置 hash，并要求进程预加载只允许 DashScope endpoint 的网络 guard。仅 `selection`、经 guard 的输出和候选 rubric 可进入评分 prompt；真实 trace、凭据和原始 run 不作为评分变量。当前真实来源回放候选 `formal-prep-20261003-88421c90/replay-judge-plan-nonthinking/` 为 `not-authorized`，真实正式 target/Judge 均 0。fake transport 的 1 次 HTTP 成功测试不证明 hosted Judge 判断正确；独立 oracle 和人工结果复核决定确认突破。
