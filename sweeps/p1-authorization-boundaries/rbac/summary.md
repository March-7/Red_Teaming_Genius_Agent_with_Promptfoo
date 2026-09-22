# rbac sweep summary

- Group: `p1-authorization-boundaries`
- Inventory status: `blocked-prerequisite`
- Prerequisites: second_role, rbac_matrix
- Disposition: `skipped-blocked-prerequisite`
- User decision: 2026-09-19，当前只有一个 Genius 测试账号，暂时跳过本类别
- Baseline run: not run
- Generated attack samples: 0
- Genius target evaluations: 0
- Judge evaluations: 0
- ASR: undefined

当前 Qwen 与 DeepSeek target 只是在同一 `GENIUS_AUTHORIZATION` 下切换模型
profile，不构成两个真实角色。提示词中自称 `user` 或 `admin` 不能替代第二身份与可核验
的 RBAC matrix，因此本类别不计为安全通过，也不计入已完成 basic 的类别数。

仅在未来具备两个真实测试角色、隔离的合成资源和经控制面验证的
`role × resource × action` allow/deny 矩阵后，才可在本任务恢复准备，并重新取得用户的
probe 与正式开始授权。

This file is trackable and contains only deterministic summary metadata.
Raw trace and evaluation artifacts are stored under the Git-ignored `runs/` directory.
