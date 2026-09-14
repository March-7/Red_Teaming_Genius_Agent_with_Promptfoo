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
- 每次只测试一个 plugin。当前默认每轮 10 个样本，`basic`，生成和 eval 并发均为 2。
  实际参数以该 plugin 的配置和本轮显式 CLI override 为准，并写入 run manifest。
- 在新 plugin 任务里，先读取并提供该 plugin 的官方文档网页地址，解释测试内容、
  允许行为与失败判据，给出两个明确标注为说明用途的输入样例，以及本轮配置。
  等用户明确确认开始后，才生成用例或调用 target。`sweep:preview` 是离线预览入口。
- 每轮结束后，向用户报告样本总数、有效数、错误/待复核数与 ASR 分子/分母；逐一列出
  攻击成功样本的编号、输入、关键输出、Judge 理由和 trace/oracle 证据。
  区分 Judge 判定的候选与人工复核确认的漏洞，不把评分错误算作攻击成功。
- 不预设“ASR 很低”的阈值，不自动升级 strategy。用户决定是否在同一 plugin 下追加
  10 个 `jailbreak:meta` 样本；追加前说明 Cloud 数据流和每样本 `numIterations` 预算。
  10 个 meta 样本不等于仅 10 次 target 调用，且不得混入额外 basic 样本。
- 每轮和每个类别结束后都暂停。仅在用户认为该类别测试充分并明确要求继续时，
  才为下一个 plugin 新建任务；不得自动扫完整 P0 或进入 P1。
- 详情与命令见 `docs/genius_plugin_sweep.md`。本地凭据、真实 trace 和 run 产物不得
  放入新任务提示、提交或外发；保持默认 unbound approval policy。
