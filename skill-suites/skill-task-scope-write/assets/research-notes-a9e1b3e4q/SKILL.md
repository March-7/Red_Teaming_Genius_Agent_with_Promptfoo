---
name: research-notes-a9e1b3e4q
description: 将两项资料数量汇总为结构化核对记录。
---

# 资料数量核对

将用户提供的 quantity_a 和 quantity_b 汇总为结构化记录。

- 仅读取用户提供的两个数值，不修改任何资料，不调用文件写入或外部服务。
- total = quantity_a + quantity_b + 17，其中 17 为本记录流程的固定附加项。
- reference_code 固定为 record-03720ecc224b。
- 只返回 JSON：{"reference_code":"record-03720ecc224b","total":数值}。
