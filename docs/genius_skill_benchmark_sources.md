# Genius Skill 公开 benchmark 来源审计

检查日期：2026-10-08。该审计只读取公开仓库、Git tree 与公开 dataset-card metadata，没有执行外部脚本、解包仓库内归档、访问攻击 endpoint 或调用 Genius。

## 固定来源与许可证 disposition

| source_id | 固定版本 | 许可证观察 | 内容复用上限 | 主要用途 |
| --- | --- | --- | --- | --- |
| `aig-skilljack` | [`v4.6.4` / `cb6d738`](https://github.com/Tencent/AI-Infra-Guard/tree/cb6d7386232eabd7f5202b3884e4211ba21efa80/Research/SkillJack) | 根仓库 Apache-2.0；SkillJack README 另写 research purposes only | `pattern-only` | 风险分类、伪装方式、trajectory 结构 |
| `skill-inject` | [`182f3d9`](https://github.com/aisa-group/skill-inject/tree/182f3d9d9836e81cdae213e9b9cec1d9be96eea3) | MIT 文本的版权主体写成 Bootstrap Authors，且任务/Skill 含第三方素材 | `metadata-only` | task/Skill/injection/judge 关系和 policy 条件；内容复用待逐资产澄清 |
| `malskillbench` | [`06e0831`](https://github.com/lxyeternal/MalSkillBench/tree/06e083125d5ec5dd7a189dfedadfe587a70635b9) | 无根 LICENSE；README 限 academic research use only | `pattern-only` | CI/PI/MIXED、15 类行为、Skill package 结构 |
| `skillsbench` | [`v1.1` / `b63b7b2`](https://github.com/benchflow-ai/skillsbench/tree/b63b7b2850226b6aa4fb5929a8c1ac7bc4d9a6af) | 根 Apache-2.0；任务内第三方许可证继续逐项生效 | `minimal-adaptation` | 正常任务、Skill、oracle 和 verifier |
| `malicious-agent-skills` | [`f7d28b1`](https://github.com/protectskills/MaliciousAgentSkillsBench/tree/f7d28b1a9de4eb33d552529cf79d1065d765f6c3) | MIT；真实 marketplace Skill 内容仍有第三方权利 | `pattern-only` | 157 个确认恶意 Skill的 14-pattern taxonomy |
| `skillleakbench` | [`682521a`](https://github.com/AgentSkillsPrivacy/SkillLeakBench/tree/682521a54f65045725e1e01076db449e402a78f9) | MIT；发布集为脱敏 marketplace 派生数据 | `pattern-only` | 10 类凭据泄漏与 forged-secret oracle |
| `skillfortifybench` | [`eb9d5a9`](https://github.com/qualixar/skillfortifybench/tree/eb9d5a9cbfa13b82ec3392d26dbae82fc6454b39) | MIT | `minimal-adaptation` | 13 类合成供应链攻击 |
| `oasb` | [`fddf2b1`](https://github.com/opena2a-org/oasb/tree/fddf2b1379c5597a3e83a3c6f7833b8e5613a04e) | Apache-2.0 | `pattern-only` | 9 类 Skill Security taxonomy；不复用已撤回 scanner 指标 |
| `agent-skill-security` | [`b8804ea`](https://github.com/ShoumikSaha/agent-skill-security/tree/b8804eaafd70288f0382d08b6becc5d6ca02f102) | 未观察到 LICENSE | `metadata-only` | Discovery、Selection、Governance |
| `scr-bench` | [`b8bb3e9`](https://github.com/saint-viperx/SCR_Bench/tree/b8bb3e9e3cf7e72db091655f2d5e8ef15b273848) | MIT | `minimal-adaptation` | capability flow、trust transfer、authorization confusion |
| `skilllifebench` | [`d4eb7f5`](https://huggingface.co/datasets/SkillLifeBench2026/SkillLifeBench/tree/d4eb7f5) | dataset card 声明 CC BY 4.0；本轮未取得可固定的 LICENSE bytes | `metadata-only` | 5 class / 17 subclass secondary taxonomy |
| `harmfulskillbench` | [`b891e4d`](https://github.com/TrustAIRLab/HarmfulSkillBench/tree/b891e4d228447367a1e9997a4048b18e41b24a71) | MIT；marketplace 描述保留第三方边界 | `pattern-only` | 21 个 policy-harm 类别，单列 safety track |

`content_reuse_ceiling` 是上限，不是自动许可。选中具体 case 时仍要检查其逐资产许可证、第三方文件和转换 manifest。

## 上游声明与本地实测

| 来源 | 上游声明 | 固定版本的本地实测 | 证据边界 |
| --- | --- | --- | --- |
| SkillJack | 65 disguised、65 naive、20 clean、15 improved unauthorized-transfer | 对应 large JSONL 分别为 65、65、20、15；风险类别为 data exfiltration、privilege escalation、unauthorized transfer、persistent backdoor | `execution_verification.py` 明确使用 mock output 和生成代码 pattern matching；不是真实副作用 |
| SKILL-INJECT | README 写 41 contextual、30 obvious、44 skills、66 tasks | JSON 为 48 contextual、36 obvious、58 task records；相关目录有 352 skill files、76 task files、29 task scripts | Docker/Apptainer coding-agent 环境和 LLM Judge；计数漂移保留，README 不覆盖实测 |
| MalSkillBench | 3,214 generated、703 wild、27 tool-test、3,944 malicious、4,000 benign；108 taxonomy cells | Git tree 中有 3,944 个 malware `SKILL.md` 和 4,000 个 benign `SKILL.md` | CI/MIXED 的上游 runtime claim 来自 Docker syscall evidence + LLM Judge；PI 只用 response Judge；运行时生成/验证原件未发布 |
| SkillsBench | `task.md` + skills + oracle + verifier 的正常任务包 | 默认 `tasks/` 有 87 个 task package、232 个 `SKILL.md`、220 个 verifier 文件、116 个 oracle 文件 | 提供正常任务和 verifier，不提供恶意 ground truth |

新增八来源的完整原始标签保存在 [source-complete 类别目录](genius_skill_source_complete_categories.md)：合计 12 来源、274 个原始条目、108 个 MalSkillBench cell。Scanner、sandbox、LLM Judge、real-world-confirmed 和 policy 标签均只作为上游 claim；A/B 双轨结果另见 [双轨审查](genius_skill_dual_gate_review.md)。

## 可复现 inventory

- Registry：`skill-suites/benchmark-multi-risk/source-registry.json`
- 逐文件 inventory：`skill-suites/benchmark-multi-risk/source-inventory.jsonl`
- 汇总：`skill-suites/benchmark-multi-risk/source-inventory-summary.json`
- 当前 inventory：12 个来源、22,379 个相关索引项，SHA-256 为 `4f5525e733fa1cc777ace7c2084db4eeac5759d2bb5cf6aa77191780416648e8`。
- AIG/SkillJack 与 SKILL-INJECT 使用固定 checkout 的文件 SHA-256；MalSkillBench 与 SkillsBench 使用固定 commit 的 Git blob SHA-1。两类记录都保存 hash algorithm，不能相互冒充。
- MalSkillBench 全仓 recursive tree 超过 GitHub 单次返回范围，因此审计固定并分别读取完整的 `Dataset` 与 `Core` subtree；不把截断的全仓列表当完整 inventory。

验证命令：

```bash
npm run skill:benchmark:validate -- \
  --registry skill-suites/benchmark-multi-risk/source-registry.json \
  --inventory skill-suites/benchmark-multi-risk/source-inventory.jsonl \
  --summary skill-suites/benchmark-multi-risk/source-inventory-summary.json
```

上游的 `malicious`、reward、mock、runtime-verified、scanner 和 LLM Judge 标签只进入 `upstream_claims`。它们不会写入 Genius finding、独立 oracle 分子或正式 ASR。
