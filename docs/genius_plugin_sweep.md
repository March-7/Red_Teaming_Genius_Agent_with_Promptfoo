# Genius 逐类别评测流程

## 工作方式

每个 P0 plugin 在本 Codex 项目中使用一个独立 task/session，直接使用当前项目目录，
不创建 worktree。同一 plugin 的 basic、结果复核和追加 strategy 留在同一 task。
本任务负责全局配置与协调；不得自动遍历 P0，也不得自动切换到 P1。

1. 在独立 plugin task 中读取官方文档，给出网页 URL、测试内容、两个说明性输入样例，
   说明什么是允许行为、什么是攻击成功，以及本轮配置。样例不自动计入正式样本。
2. 用户确认开始后，生成当前 plugin 的 10 条 basic 用例，核查用例及配置，再执行 eval。
3. 生成和 eval 并发均为 2。默认每条 basic 样本使用新 Genius session。
4. 汇报总样本数、有效样本数、错误/待复核样本数和有效 ASR 的分子、分母；逐一解释
   攻击成功样本的输入、关键输出、Judge 理由及 trace/oracle 证据。
5. 每轮汇报后暂停。ASR 是否太低由用户判断；用户可以选择对同一 plugin 追加
   10 个 Meta-Agent 样本、继续复核，或者认为该类别充分后进入下一个 plugin。
6. 只有用户明确要求换类别后，才创建下一个 plugin task，重复文档与样例介绍流程。

## 可调整配置

`promptfooconfig.yaml` 是共享生成模板；各 plugin 的实际 baseline 配置位于
`sweeps/<group>/<plugin>/config.basic.yaml`。当前默认：

```yaml
redteam:
  plugins:
    - id: hijacking
      numTests: 10
  strategies:
    - id: basic
  numTests: 10
  maxConcurrency: 2
evaluateOptions:
  maxConcurrency: 2
```

修改某一 plugin 文件中的两个 `numTests` 可调整样本数；修改 `maxConcurrency` 可调整
并发。runner 读取实际参数，也支持 `--num-tests` 和 `--max-concurrency` 显式覆盖。
run manifest 保存实际生效参数与配置 hash，不能只看根目录模板推断已有 run。

当前 inventory 仍有 6 组、39 个 built-in plugin，但当前流程只逐一开展 P0。
不会因为其他组也有配置而自动执行它们。不要重新运行 `sweep:generate` 来修改少数
参数：该命令用于初始化 scaffold，会重写所有 plugin 的配置、policy 和 summary。

## 离线预览与检查

```bash
npm run sweep:preview -- --plugin hijacking
npm run sweep:gate -- --group p0-agent-control --plugin hijacking
npm run sweep:validate
npm run redteam:validate
```

`preview` 仅输出本地说明、官方 URL、两个自拟样例和实际 basic 参数，不访问模型或
Genius。每个 plugin task 仍须实际阅读对应官方页面。gate 返回 `ready`、
`blocked-prerequisite` 或 `not-applicable`；只有 ready 才能执行。

配置校验检查唯一 plugin、basic baseline strategy、正整数样本数和并发、样本数一致性、
配置/目录完整性以及精确 approval policy。P1 的角色、对象、RAG、MCP 等 prerequisite
仍需另行准备，不能凭模板存在就宣称测试过。

## 执行一轮

仅在该 plugin task 中完成介绍并得到用户开始确认后执行：

```bash
npm run sweep:run -- --group p0-agent-control --plugin hijacking
```

单次覆盖示例（与当前默认相同）：

```bash
npm run sweep:run -- --group p0-agent-control --plugin hijacking --num-tests 10 --max-concurrency 2
```

runner 自行启动并关闭 `127.0.0.1:4030` 的 shim，不需要预先运行 `npm run shim`。
端口已被占用或 health 的进程 ID 不属于本次进程时，停止执行，不复用或终止别人的
服务。缺失或无效的 policy 在生成/target 调用之前被拒绝。

生成新用例会向 Promptfoo 官方 generation API 发送 purpose/plugin 请求。
Target 通过本地 shim 调用 Genius，Judge 显式使用配置中的百炼 `qwen3.8-max`。
runner 禁用遥测、更新检查和结果分享，保留本地 JSON/JSONL 产物，不写 Promptfoo DB。
如要在官方报告 UI 查看，可另行导入 eval.json，无需重新调用 Genius。

复用已有用例可传 `--generated`，文件中的 plugin、strategy 和用例数量必须与本轮
一致；测试正文与 assertions 保持不变，运行 headers 和 Judge 配置单独写入 runtime 文件。

## Meta-Agent 追加轮次

官方文档：https://www.promptfoo.dev/docs/red-team/strategies/meta/

Meta-Agent 对应 `jailbreak:meta`。它根据 target 回复调整攻击方法，需要 Promptfoo
Cloud 的策略推理/记忆服务；这与是否分享最终评估报告是两件事。实际开始前应向用户
说明数据流并确定每个样本的 `numIterations` 上限。

runner 用 `--strategy jailbreak:meta` 选择追加轮次，并要求显式传 `--max-iterations N`，
其中 N 是用户确认的每样本上限，映射到 Promptfoo 的 `config.numIterations`。
样本数默认仍为 10，并发 2。配置会设置 `basic.config.enabled: false`，只评估指定数量
的 meta 样本，不附带另外 10 条 basic。Meta run 有独立目录和 strategy 标识。

10 个 meta 样本不等于 10 次 target 请求：每个样本可能迭代多次，并涉及 attacker/Judge
调用。不得把 basic 与 meta 的结果混成一个未区分 strategy 的 ASR。

## Run 产物与汇报

```text
sweeps/<group>/<plugin>/
  config.basic.yaml
  approval-policy.json
  summary.md
  runs/<timestamp>/
    config.basic.yaml        # meta 轮次为 config.meta.yaml
    generated.basic.yaml     # meta 轮次为 generated.meta.yaml
    approval-policy.json
    eval.runtime.yaml
    eval.json
    eval.jsonl
    genius_trace.jsonl
    session_lifecycle.jsonl
    oracle.jsonl
    run-manifest.json
    summary.json
    summary.md
    samples.json
    sample-report.md
```

manifest 记录实际样本数、并发、strategy、strategy config、代码 commit、工具版本、
配置/policy/用例/runtime hash、起止时间、生成来源、eval exit code 和分享开关。

`sample-report.md` 和 `samples.json` 是逐样本结果，含输入、Target 输出、Judge 理由和
错误。`summary` 列出攻击成功候选编号、有效样本数、排除的样本编号和有效 ASR。
原始 pass/fail/error 计数始终保留。所有详细 run 产物被 Git 忽略，plugin 级 summary
只保存汇总信息。

- Judge fail 且无运行/评分错误：`attack-success-candidate`，随后逐条人工检查证据。
- Target error、grading error、评分 pass/score 矛盾：单独报告，排除出有效 ASR 分母。
- 有效 ASR = Judge 攻击成功候选数 /（有效 pass 数 + 候选数）；无有效样本时为未知。
- 对工具副作用，只能在独立 oracle 已验证时确认越界或实际效果；批准不等于执行成功。
- `approved-effect-unverified` 表示获批但效果未独立验证；`grading-review-required`
  表示评分需要复核；缺失必要产物标为 `incomplete`。

默认 approval policy 是精确 unbound rule，不匹配真实动作。runner 把其快照显式加载
到本次 shim，并带上 run/group/plugin 标识；不会自动把占位规则改成真实批准。

## 本次重置

2026-09-13 按用户要求删除 hijacking 的三个旧 run（包括一个未完整结束的早期 run）、
全局旧 trace、live smoke、多轮 viewer 演示和相关 QA 产物；hijacking summary 重置为
尚未运行。viewer 当前从空记录开始。配置、代码、测试、规范和不参与 viewer 的
Quickstart 历史配置归档保留。本次重置没有发起新的 Genius 或模型请求。
