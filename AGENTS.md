# 项目 Agent 协议

## OpenSpec 语言

- `openspec/` 下的 planning artifacts（包括 `proposal.md`、`design.md`、
  `tasks.md` 和 `specs/**/spec.md`）默认使用简体中文表述。
- 当领域词和实现词是标识符或既有术语时，保留原始英文形式（例如 `plugin`、
  `strategy`、`sandbox`、`RBAC`、`approval`、`trace`、API/error code、文件路径和
  命令）。

## 逐类别评测协议

- 当前任务负责全局流程与配置；每个具体 P0 plugin 必须在本 Codex 项目中新建一个
  独立 task/session 开展。用户已指定新任务直接使用当前项目本地目录（local），不创建 worktree。使用 Codex `create_thread` 创建用户可见任务，不把 subagent
  当作用户要求的新 session。同一 plugin 的 basic、结果复核和追加 strategy 留在同一任务。
- 2026-09-15 用户指定：后续新建测试类别任务时，Codex `create_thread` 显式使用
  `model=gpt-5.6-sol`、`thinking=high`，继续使用当前项目 local 目录。
  这是执行测试工作的 Codex 模型设置，不改变被测 Genius 的双模型配置。
- 每次只测试一个 plugin。当前默认每轮 20 次正式评测：同一组 10 条 `basic` 输入分别
  交给 Qwen3.8-Max（`model_profile=default`）和 DeepSeek-V4.1-Flash
  （`model_profile=deepseek-v4.1-flash`），两组均显式请求 `reasoning_effort=high`、
  `thinking=on`。生成和 eval 总并发均为 2，`numTests` 表示每模型输入数，不是总次数。
  实际参数以该 plugin 的配置和本轮显式 CLI override 为准，并写入 run manifest。
- 在新 plugin 任务里，先读取并提供该 plugin 的官方文档网页地址，解释测试内容、
  允许行为与失败判据，给出两个明确标注为说明用途的输入样例，以及本轮配置。
  等用户明确确认开始后，才生成用例或调用 target。`sweep:preview` 是离线预览入口。
  2026-09-15 用户再次明确：后续“启动下一类别”先创建并准备任务，介绍完必须询问
  是否开始，收到用户明确回复确认后才正式生成或执行。不得沿用此前类别的开始授权。
- 每轮结束后，向用户报告样本总数、有效数、错误/待复核数与 ASR 分子/分母；逐一列出
  攻击成功样本的编号、输入、关键输出、Judge 理由和 trace/oracle 证据。
  区分 Judge 判定的候选与人工复核确认的漏洞，不把评分错误算作攻击成功。
  必须分别报告每个模型的样本数和 ASR；run manifest 保存模型目录快照及请求参数，
  不把发送的推理强度或正常响应当作后端实际档位的证明。
- 2026-09-14 用户已授权删除三个既有 P0 plugin 的旧结果，并在原任务重跑新双模型配置；
  这三个任务无需重复索要开始许可。仍须保持单 plugin 串行运行、先检查真实适用性，
  hijacking 的用途边界不足不得伪装成有效通过。新类别仍遵循介绍后确认协议。
- 2026-09-15 V4.1 迁移授权覆盖上述旧清理要求：从此保留现有历史 run、summary 中的
  旧模型标识与结果；新 run 的第二模型为 DeepSeek-V4.1-Flash，不回写历史。
  用户已授权在原任务串行复测 system-prompt-override、excessive-agency、tool-discovery、
  overreliance、hallucination，无需再次索要这些 rerun 的开始许可。当前 goal-misalignment
  先完成已授权本轮，再逐项交接上述五类；每项结束并释放 4030/全项目锁后才交接下一项。
  hijacking 不进入此队列；其他新类别仍必须先介绍再确认。
- 新 run 必须由公共 runner 在 Judge 前挂载 sensitive output guard 并记录 hash；
  单条测试不得覆盖该 guard。守卫拦截为待本地复核的错误，不算攻击成功或安全通过。
- 不预设“ASR 很低”的阈值，不自动升级 strategy。用户决定是否在同一 plugin 下追加
  10 个 `jailbreak:meta` 样本；追加前说明 Cloud 数据流和每样本 `numIterations` 预算。
  10 个 meta 样本不等于仅 10 次 target 调用，且不得混入额外 basic 样本。
- 每轮和每个类别结束后都暂停。仅在用户认为该类别测试充分并明确要求继续时，
  才为下一个 plugin 新建任务；不得自动扫完整 P0 或进入 P1。
- 详情与命令见 `docs/genius_plugin_sweep.md`。本地凭据、真实 trace 和 run 产物不得
  放入新任务提示、提交或外发；保持默认 unbound approval policy。
