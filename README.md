# Red_Teaming_Genius_Agent_with_Promptfoo

用于学习和实践 Promptfoo Red Team Quickstart 的独立 Git 项目。

当前状态：Genius Agent target、本地 shim、Application Details、三个 plugins、
Basic strategy，以及百炼 `qwen3.8-max` attacker/Judge 均已配置。首次小规模扫描
已完成，结果为 5 个有效样本通过、1 个生成格式错误。

当前 target 为网页版 Genius Agent。本项目已内置独立的
OpenAI-compatible Genius shim，不再在运行时依赖其他项目的代码或配置。
Promptfoo 通过 `http://127.0.0.1:4030/v1` 与本地 shim 通信，由 shim 负责
Genius 会话创建、短期凭证刷新、SSE 解析、错误分类和 trace 脱敏。

## Local commands

```bash
# 安装锁定的 Python shim 依赖
uv sync

# 运行纯离线 shim 测试，不调用 Genius 或任何模型
npm run test:shim

# 在本地 .env 配置完成后启动 shim
npm run shim

# 启动 Promptfoo Red Team 配置页面
npm run redteam:setup

# 离线校验根目录 promptfooconfig.yaml，不调用 target 或模型
npm run redteam:validate

# 使用根目录配置生成用例并运行扫描
npm run redteam:run
```

配置与安全说明见 [docs/genius_shim.md](docs/genius_shim.md)。真实 JWT 只应保存在
Git 忽略的 `.env` 中，不应粘贴到聊天、日志、Issue 或报告里。

## Promptfoo files

- `promptfooconfig.yaml`：主运行配置，也是 `promptfoo redteam run` 的默认输入。
- `redteam.yaml`：最近一次生成的 6 条测试用例，可用于审计和复现。
- `.env.promptfoo`：百炼 attacker/Judge 凭证，仅存本机且被 Git 忽略。
- `.env`：Genius 网页会话凭证，仅由本地 shim 读取且被 Git 忽略。

## Safety boundary

- 未确认 target、授权范围和测试环境前，不执行攻击或扫描。
- 优先使用沙箱、测试账号和非生产环境。
- 运行前检查 Promptfoo 的远程生成、评分、遥测和数据传输设置。
