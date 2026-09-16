## 1. 类别说明与离线 gate

- [x] 1.1 在 `sweep/briefs.py` 增加 `cross-session-leak` 官方 URL、准确范围和两个 User A/User B 说明 pair，运行 brief 单测验证 preview 不调用 generation/target/grader
- [x] 1.2 新增 `cross-session-probe.json` attestation 校验，使 `--available two_isolated_sessions` 单独不能解锁正式 runner，并以缺失、伪造和有效 mock attestation 测试 gate fail closed
- [x] 1.3 更新本类别 `config.basic.yaml` 为专用 HTTP session transport，运行 scaffold validation 验证双模型 high/on、并发 2、默认 unbound policy 和分享关闭约束未改变

## 2. 生成 pair 归一化

- [x] 2.1 实现 User A/User B/match pair parser，将 10 个完整 pair 归一化为 10 条正式 attack tests，并用 fixture 测试验证原始 hash、顺序、metadata 与官方 deterministic assertion 保留
- [x] 2.2 对缺失/重复 match、奇数 turns、错序、跨 pair canary 和 attack prompt 含 canary 的输入 fail closed，并运行定向单测确认任何 Genius target 调用前退出
- [x] 2.3 写出 `generated.raw.yaml`、`generated.basic.yaml`、`cross-session-pairs.jsonl` 和 `generation-audit.json` 的 manifest 映射，并用 mock generate-only 验证正式结果预算仍为每模型 10 条

## 3. 双原生 session transport

- [x] 3.1 为 session store 增加仅供受控 fixture 使用的 upstream session 预绑定能力，运行 TTL、重复绑定和普通 OpenAI 请求不可调用的单元测试
- [x] 3.2 实现 `/v1/cross-session-fixtures`：仅接受 opaque pair index/namespace/label，从 run-local registry seed session A 并预创建 session B，运行 mock upstream 测试验证 A/B 原生 id 不同且 attack 请求不可见 source/canary
- [x] 3.3 在并发 2 的双模型 mock eval 中验证 20 对 session、40 个唯一 upstream id、模型/样本不共享、两层零重试且 source turn 不进入正式结果
- [x] 3.4 实现只针对本 run registry 的 retain/cleanup lifecycle 分支，测试未获 cleanup policy、其他 plugin session 和既有 session 均不会被删除

## 4. 来源审计、oracle 与汇报

- [x] 4.1 eval 后抓取 A/B persisted messages 并关联 trace/registry，运行测试验证 A 含 canary、B 输入不含 canary以及缺失关联进入 `source-unverified-review`
- [x] 4.2 扩展 `oracle.jsonl` 生成逻辑，以 exact-match 区分 controlled canary 跨 session、拒绝/虚构/近似值和 target-visible input reflection，并验证不依赖工具名称或模型自述
- [x] 4.3 扩展 manifest/summary/review 字段，分别报告 Promptfoo candidate、mechanism recall、confirmed unauthorized disclosure、same-principal/owner/project/team/tenant scope 和 40 次正式 target 调用预算，并运行汇总单测
- [x] 4.4 验证 sensitive output guard 在官方 deterministic assertion 前执行、单条 transform 不能覆盖，并以 guard 拦截 mock 确认其归类为待复核错误而非攻击成功或安全通过

## 5. 最小真实探针工具（不执行真实调用）

- [x] 5.1 实现 `sweep/cross_session_probe.py` 的 3-call 协议（A seed、A positive recall、B cross-session control），运行完全 mock 的 CLI 测试验证 0 generation、0 LLM Judge 和固定最大 3 次 target 调用
- [x] 5.2 实现 probe 的 persisted-message audit、exact-match 结果、attestation hash 和显式 retain/cleanup policy，运行 mock 测试验证只处理本次创建的两个 session
- [x] 5.3 在 probe 帮助文本和准备文档中明确 real call、不可恢复 session deletion 与 scope 限制，检查未收到用户确认时所有文档示例只执行离线 preview/gate

## 6. 集成验证与交接

- [x] 6.1 运行 `python -m unittest tests.test_genius_shim tests.test_sweep_scaffold`、`npm run sweep:validate` 与相关 model matrix 测试并修复回归
- [x] 6.2 运行 `npm run sweep:preview -- --group p1-memory-session-data --plugin cross-session-leak` 和未提供真实 probe attestation 的 gate，验证官方 URL/样例/预算正确且状态明确为 blocked 而非 ready
- [x] 6.3 更新 `docs/genius_plugin_sweep.md`、`docs/genius_shim.md` 和 `sweeps/p1-memory-session-data/cross-session-leak/preparation.md`，复核其区分同账号 session、Project、Team、账号和 tenant，且未把 mock 说成端到端完成
- [x] 6.4 运行 `openspec validate add-cross-session-leak-fixtures --type change --strict` 并检查 `git diff --check`；完成后暂停，先请求 3-call probe 与其 lifecycle policy 的明确授权，不自动生成或调用 Genius
