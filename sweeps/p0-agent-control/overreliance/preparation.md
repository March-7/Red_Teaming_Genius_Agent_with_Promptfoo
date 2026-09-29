# overreliance V4.1 basic 复测准备

- 准备日期：2026-09-15
- 官方文档：https://www.promptfoo.dev/docs/red-team/plugins/overreliance/
- 当前状态：离线准备完成，等待 goal-misalignment 队列按既定顺序明确交接执行权。
- 执行边界：收到内容包含“V4.1 队列执行权交接”的任务消息前，不运行 `sweep:run`，
  不生成用例，不调用 target 或 Judge。

## 用户授权与队列位置

用户已授权在原任务串行复测
`system-prompt-override → excessive-agency → tool-discovery → overreliance → hallucination`。
本类别无需再次索要开始许可，但该授权不允许越过串行交接。当前执行权仍在前序任务；
本任务完成后只有在停止本轮进程并确认 4030 与全项目锁释放后，才向 hallucination 任务
发送下一次交接。

## 复用输入

复用最近一轮已人工复核的同组 10 条输入与 assertions：

`sweeps/p0-agent-control/overreliance/runs/2026-09-14T17-26-41/generated.basic.yaml`

- SHA-256：`79cb946e87a59eca6f5d0c08dd2bbfdc9588cc1dc659c0b5d222c7c2c17c1740`
- 10 条非空且互异的输入；全部 `metadata.pluginId=overreliance`
- 每条 assertion 均为 `promptfoo:redteam:overreliance`
- 无 per-test `options.transform`，不会覆盖公共 sensitive output guard
- 不修改输入正文或 assertions；新 run 复制来源并在 manifest 记录绝对路径与 hash

该生成文件的历史 target 仍正确保留为 Qwen3.8-Max + DeepSeek-V4-Flash。这只是旧 run 的
来源快照，不得改写。公共 runner 会从当前 plugin config 重新绑定本轮两个 target，因此
新 run 必须实际执行 Qwen3.8-Max + DeepSeek-V4.1-Flash，不能把旧 V4 标签带入本轮结果。

历史人工复核基线位于同一 run 的 `review.md` / `review.json`：Qwen 当时有效 8、2 个
target error、ASR 0/8；DeepSeek-V4-Flash 有效 10、确认 1 个 overreliance、ASR 1/10。
本轮只可比较相同输入下的观测差异；模型版本、运行时间、服务状态和 Judge 随机性均已
变化，不能把差异直接归因为 V4.1 版本升级。

## 当前矩阵与 runner 门禁

- Qwen3.8-Max：`model_profile=default`，请求 `reasoning_effort=high`、`thinking=on`
- DeepSeek-V4.1-Flash：`model_profile=deepseek-v4.1-flash`，请求
  `reasoning_effort=high`、`thinking=on`
- 同一组 10 条输入，每模型 10 次，共 20 次；eval 总并发 2；每条独立 session
- config SHA-256：`cdd6f8fd6831fea7b12bade6a55a0983a82d6699bc2f6621b66f56c0c515e098`
- approval policy SHA-256：`2433a5927cda8d3f284e9a57c09a375b2637d583cf5d0dd5c7aecfe533a82459`
- 保持精确 unbound approval policy；结果分享、遥测和 Promptfoo DB 写入关闭
- V4.1 目录已由共享迁移门禁确认启用并声明支持 high；后端实际档位仍为
  request-only / unverified

公共 runner 在 `prepare_runtime_config` 中把
`sweep/sensitive_output_guard.cjs` 强制挂到 `defaultTest.options.transform`，在 Judge
assertions 前执行，并拒绝不同的 default/per-test transform。guard 当前 SHA-256 为
`dfc7a99c73e4ae96114eefa6b0315e5530161907d8e6f423f29434d20f18e071`。新 run manifest
必须记录 guard 路径、该 hash 和 `per_test_overrides_checked=true`。

runner 创建新 run 时还会把当前 plugin summary 保存成 `previous-plugin-summary.md`；
当前历史 summary SHA-256 为
`670c2bc9ad24774c667684eba97c423a381d39d14db0667c07e63416635fbf21`，新 manifest 应保存
对应 hash。该快照用于保留 V4 历史，不能被新 V4.1 结果重写。

## 离线核验结果

- `sweep:preview`：V4.1 双模型矩阵、每模型 10 条、总数 20、并发 2
- inventory gate：`ready`
- `sweep:validate`：通过
- `tests.test_model_matrix` + `tests.test_sweep_scaffold`：42/42 通过
- 来源 YAML：10 条输入、10 个唯一 prompt、plugin/assertion 一致、0 个 per-test transform
- `git diff --check`：通过
- 准备检查时 4030 无监听进程，`logs/.sweep.lock` 无持有者
- 未创建新 run，未调用生成器、target 或 Judge

首次只读 YAML 检查片段曾因把当前 CommonJS `js-yaml` 当成 ESM default export 而退出；
随后使用 CommonJS 重新执行并完成上述结构核验。该错误不涉及 runner、配置或任何模型调用。

## 收到交接后的唯一正式入口

```bash
npm run sweep:run -- --group p0-agent-control --plugin overreliance \
  --generated sweeps/p0-agent-control/overreliance/runs/2026-09-14T17-26-41/generated.basic.yaml
```

正式执行前重新确认交接消息、4030 与全项目锁；不得改成 generate-only、单模型脚本或其他
输入文件。runner 必须以新 run 的 runtime/manifest 通过 config、target matrix、guard、
来源 hash 和 previous-summary 快照门禁后才启动 shim/eval。完成后不自动重试、补样、追加
meta 或启动其他类别；先人工复核、更新本 plugin summary 与全局进度，再释放资源并交接。
