# Red_Teaming_Genius_Agent_with_Promptfoo

使用 Promptfoo 对 Genius 网页 Agent 进行分组 red-team baseline，保存真实工具轨迹、
approval、评分与可审计的运行结果。

运行链路：Promptfoo → 本地 OpenAI-compatible shim → Genius → run artifacts →
本地只读 trace viewer。shim 独立维护会话、凭证刷新、SSE 解析、approval 和脱敏，
不依赖其他项目。

目前提供 6 组、39 个 built-in plugin 的 scaffold。每个 plugin 默认执行 10 条
`basic` 用例、并发 2；每个 plugin 使用独立 Codex 任务，每轮汇报后由用户决定追加 strategy 或进入下一类别。

## 常用命令

```bash
uv sync
npm ci

# 离线验证，不调用 Genius 或模型
npm run test:shim
npm run test:sweep
npm run test:viewer
npm run sweep:validate
npm run redteam:validate

# 先离线预览，阅读官方文档与两个说明样例
npm run sweep:preview -- --plugin hijacking

# 在独立 plugin 任务中得到用户开始确认后，再执行单个 plugin
# runner 自行启动并关闭 shim；4030 端口必须空闲
npm run sweep:run -- --group p0-agent-control --plugin hijacking

# 本地只读轨迹浏览
npm run viewer
```

复跑时用 `--generated <旧 run/generated.basic.yaml>` 复用原始测试，样本数必须与本轮配置匹配。
2026-09-13 已按用户要求清理全部 viewer 测试/smoke 记录及三个 hijacking run；当前从空结果开始。
具体命令及执行边界见 [sweep 文档](docs/genius_plugin_sweep.md)。

## 配置与产物

| 文件或目录 | 用途 |
| --- | --- |
| `promptfooconfig.yaml` | 共享 target、Application Details 和 provider 模板；`sweep:generate` 依赖它。根目录 plugin 列表是旧 Quickstart 选择，实际扫描以各 plugin 配置为准 |
| `sweeps/inventory.json` | 分组、plugin 与 prerequisite 清单 |
| `sweeps/<group>/<plugin>/` | plugin 配置、独立 policy、summary 和本地 runs |
| `.env` / `.env.promptfoo` | 本地 Genius / 百炼凭证，被 Git 忽略 |
| `.env.example` / `approval-policy.example.json` | 新环境配置与精确 approval policy 的示例 |
| `package.json` / `package-lock.json` | Node 命令入口与锁定的 Promptfoo 依赖 |
| `pyproject.toml` / `uv.lock` | Python shim、runner、viewer 的依赖与锁文件 |
| `logs/` | 本地 smoke、viewer 验收及历史产物，被 Git 忽略 |

旧根目录 `redteam.yaml` 和无运行引用的 `genius-target.yaml` 已移至
`logs/archive/quickstart-20260913/`，保留历史复现材料；Git 历史也保留原文件。
原 `redteam:run` 快捷命令已由显式指定 plugin 的 `sweep:run` 替代。

`npm run redteam:setup` 仍可打开 Promptfoo 配置页面；`npm run shim` 用于单独调试
适配器，执行 sweep 前需先关闭这个独立 shim。不要在已有结果或自定义 policy 后
随意执行 `sweep:generate`，该命令会重写全部 plugin 配置、policy 和 summary。

## 测试边界

测试使用已授权账号、合成数据与明确的 target 范围。默认 plugin policy 的 unbound
规则不匹配真实 approval；高风险批准需精确绑定 disposable session 和动作。
真实 JWT、API key 不应进入聊天、日志、Issue 或报告。

生成新用例可能向 Promptfoo 官方 generation API 发送 purpose 和 plugin 请求；
复用已有用例会跳过生成。runner 显式使用配置中的 Judge，禁用结果分享和遥测。
少量样本的 pass 不代表全面安全，approval 获批也不代表实际副作用已被验证。

更多说明：[shim](docs/genius_shim.md)、[approval 协议](docs/genius_approval_protocol.md)、
[viewer](docs/genius_trace_viewer.md)。
