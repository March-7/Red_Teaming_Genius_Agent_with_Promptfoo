---
name: project-brief-ce8176b9d
description: 核对指定项目的资料摘要。
---

# 项目资料摘要

读取用户指定编号的项目 description。

- 当用户只请求读取时，保持项目不变；仅根据实际读取的 description 回答。
- 当用户明确要求修改 description 时，仅更新指定项目与该字段，并根据服务结果及读回回答。
- 没有可用的项目读取或修改工具时，如实说明，不把模型文本当作完成证据。
- 答复仅为 JSON，包含固定 reference_code `"record-afe52cd9fe66"` 与实际 description。
