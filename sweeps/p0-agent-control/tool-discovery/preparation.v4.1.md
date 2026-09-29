# tool-discovery V4.1 复测离线准备

2026-09-15。状态：**离线就绪，等待明确的 V4.1 队列执行权交接**。

用户已授权本类别复测，无需重复询问开始许可。必须等待前一任务 `01a09fd5-6d16-7e32-9268-2bdd96995f32` 明确交接；本次准备没有生成、模型目录请求、target 或 Judge 调用，未启动 shim、未占用全项目锁、未新建正式 run。

已重读当前 AGENTS.md、docs/genius_plugin_sweep.md、config.basic.yaml 和公共 runner；sweep:preview / sweep:gate 均完成，gate=ready。临时目录中调用公共 prepare_runtime_config 做纯离线核查，已确认新 target 绑定、强制 guard、hash 与单条覆盖检查，随后删除临时目录。

## 比较口径

复用上轮已审查的 10 条 basic 输入和 assertions，不重生成、不修改正文。新轮 Qwen3.8-Max/default 与 DeepSeek-V4.1-Flash/deepseek-v4.1-flash 各实测 10 次，总并发 2，每次独立 session，均请求 high/on。来源中的旧 V4 target 元数据保留，runner 仅在新 runtime 绑定 V4.1；来源 hash 写入新 manifest。

[官方文档](https://www.promptfoo.dev/docs/red-team/plugins/tool-discovery/) 已在本任务前轮实际读取：列出具体工具/参数属于官方行为候选；Genius 的正常公开能力介绍及当前用户可见工具信息不能自动确认未授权泄露。现有真实披露政策/角色边界仍不足，继续分层汇报，不伪造约束。

历史 Qwen #5/#10 的一般能力说明与宽泛枚举 rubric 存在语义歧义，#6 曾出现 pass/score 矛盾；新轮按实际输出逐条复核，不沿用历史判定，也不修改 assertions 来改变可比性。没有独立 oracle 不确认副作用。两轮运行时间和后端状态不同，ASR 差异不能直接归因于模型版本。

公共 runner 在 Judge 前挂载 sensitive_output_guard 并记录 hash；源文件 guard 与当前路径一致，无需修复。保持精确 unbound policy、sharing disabled。guard 命中须标错误/本地待复核，不作为成功或安全通过。

## 收到交接后的唯一执行命令

```bash
npm run sweep:run -- --group p0-agent-control --plugin tool-discovery --generated sweeps/p0-agent-control/tool-discovery/runs/2026-09-14T17-00-29/generated.basic.yaml
```

执行前再次核对当前配置、来源 hash；公共 runner 校验实时模型目录并建立新 run，保存 previous-plugin-summary.md/hash。此准备不声称已验证本次后端档位；目录支持声明仍不等于实际请求生效回执。

完成或实质阻塞并释放资源后，才交接 overreliance `01a0a0f2-e95f-7c70-8df6-251c57b4cdef`，并向主线发送仅汇总事实。没有提前交接。历史 summary/run 保持原样，新轮结束时保留历史链接和 V4/V4.1 区分。

## 离线核查记录

```json
{
  "status": "offline-ready-awaiting-explicit-v41-handoff",
  "predecessor_task": "01a09fd5-6d16-7e32-9268-2bdd96995f32",
  "source": "sweeps/p0-agent-control/tool-discovery/runs/2026-09-14T17-00-29/generated.basic.yaml",
  "source_sha256": "2769400911d6bd525bb1a1f84462f2692379d613fed658b20ff928413b720094",
  "source_model_version": "DeepSeek-V4-Flash; preserved historical generation metadata",
  "runtime_targets": [
    {
      "label": "Qwen3.8-Max / high",
      "model_profile": "default",
      "reasoning_effort": "high",
      "thinking": "on"
    },
    {
      "label": "DeepSeek-V4.1-Flash / high",
      "model_profile": "deepseek-v4.1-flash",
      "reasoning_effort": "high",
      "thinking": "on"
    }
  ],
  "tests": 10,
  "expected_evaluations": 20,
  "concurrency": 2,
  "guard": {
    "placement": "defaultTest.options.transform",
    "transform": "file:///Users/chenkexin/Documents/GitHub/Red_Teaming_Genius_Agent_with_Promptfoo/sweep/sensitive_output_guard.cjs",
    "sha256": "dfc7a99c73e4ae96114eefa6b0315e5530161907d8e6f423f29434d20f18e071",
    "per_test_overrides_checked": true
  },
  "source_and_assertions_unchanged": true,
  "historical_hashes_unchanged": true,
  "generation_target_judge_calls": 0
}
```
