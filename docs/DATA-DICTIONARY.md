# 数据字典

| 字段 | 类型 | 可空 | 定义 |
|---|---|---:|---|
| `run_id` | string | 否 | 输入摘要派生的稳定运行编号 |
| `source_line` | integer | 否 | 原文件物理行号 |
| `reason_code` | string | 是 | 隔离或冲突的稳定原因码 |
| `raw_value` | string | 是 | 未归一的原始证据 |
| `normalized_value` | string | 是 | 按项目规则得到的值 |
| `rule_version` | string | 否 | 计算规则版本 |
| `request_hash` | string | 否 | `(service, request_id)` 经加盐 HMAC-SHA256 的不可逆指纹，撤回关联键 |
| `masked_id` | string | 否 | 仅用于人工核对的脱敏标识（服务+短摘要），不可反推全文 |
| `deducted_count` | integer | 否 | 撤回从当前统计扣除的事件条数 |
| `deducted_errors` | integer | 否 | 撤回扣除的差错条数 |
| `error_rate` | number | 否 | 差错数/活跃数；当前统计随撤回重算，封账批次封存不变 |
| `withdrawal_notes` | array | 是 | 撤回对已封账批次的影响标注，只注明不改封存数 |

字符串编号逐字保留。金额与计量值用 `Decimal`。时间值带偏移并以 UTC 参与比较。区间统一采用左闭右开。

## 合规撤回存储约定

| 表 | 保留内容 | 不保留内容 |
|---|---|---|
| `ledger_events` | 指纹、服务、UTC 小时桶、差错标记、撤回标记 | 原文、可读请求标识、status 原值 |
| `withdrawals` | 不可逆指纹、脱敏标识、扣减计数、服务级前后差异、原因码 | 请求原文、完整可读 ID |
| `interceptions` | 指纹、服务、原行号、拦截时间、原因码 | 被拦截的迟到副本原文 |
| `sealed_runs` / `sealed_events` | 封账计数、差错率、匿名指纹快照 | 任何明文请求内容 |

撤回后原文及可读标识不可恢复；封账批次的计数与差错率为封存凭证，撤回只追加 `sealed_withdrawal_notes` 标注，不修改封存值。
