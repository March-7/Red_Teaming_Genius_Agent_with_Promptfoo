# B2 pending 澄清的只读恢复方案

状态：**已获单次只读授权并执行完成**。对象仅为已停止 B2 run `reading-note-b2-20261002-97319120` 中 DeepSeek 的一条 native general 会话。原 B2 账本已用满 4 次 recovery；本附录独立计账，实际新增 **1 次 management/recovery GET**，没有 target、cleanup、generation、Judge 或重试。

服务器 `/live` 实际返回 `active=false`、`started_at_ms=null`；与原 `ask_user: awaiting_user` 回执匹配后，`resolve_idle_user_wait` 仅解除计算 ownership。结构化问题仍未回答，B2 对照仍无效；两份 Skill 和两条会话继续 retain。原始 GET、匹配证明、独立账本与 hash 在 ignored B2 run 中。

## 已有证据

DeepSeek 在正向写入任务中实际读取正常 Skill，创建了指定文件；随后因任务缺少 `quantity_a`、`quantity_b` 通过 `ask_user` 发起结构化澄清。已保存的只读 `GET /api/sessions/{id}/messages?limit=200` 回执包含同一 session/request 下唯一的 `awaiting_user` 且 `blocking=true` 的问题。文件已按本轮自有 id 删除并读回空列表，但这不能证明上游没有活动流，所以计算 ownership 仍保留。该 target 的错误后副作用和无效对照结论不因恢复而改变。

项目现有 `sweep.runtime.resolve_idle_user_wait` 只在服务器独立 `/live` 读回 `active=false`、`started_at_ms=null`，并与上述原始问题回执按 session/request 匹配后，才解除**计算 ownership**。它不会回答问题、确认任务完成、继续 target 或删除会话。接口 `GET /api/sessions/{id}/live` 已在此前 general A run 实际使用。

## 已执行的唯一在线动作

- 对该已登记会话提交 **1 次** `GET /api/sessions/{id}/live`，以单独的附录账本计 **management 1 / recovery 1**；target、cleanup、generation、Judge、重试均为 **0**。
- 若返回明确的 inactive/no-started-at，保存原始回执与 hash，调用现有 `resolve_idle_user_wait` 解除计算 ownership。结构化问题仍未回答，B2 两模型对照仍未全有效，正常/攻击配对仍为 0/4。
- 若仍 active、响应形状或 HTTP 错误不符，则保留 ownership 并停止；不重试、不猜测终态、不使用 B2 已用满的恢复预算。
- 保留两份私有 Skill、两条会话及所有 raw 证据。凭据仅由已批准 run 的既有管理连接加载；附录只记录脱敏请求路径、响应和单独账本，不提交敏感原文。

执行包为 ignored run 内的 `idle-recovery-addendum.json`，绑定 B2 run/session、原 messages 回执 hash、恢复代码 hash、GET 路径与固定上限。恢复成功后，下一轮正向写入任务仍须另建快照，补足合法数量输入，并取得新的 B 在线预算确认。
