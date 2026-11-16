# 深度登记 多时区应用日志小时桶重算

        - 规模：中型
        - 核心规则：事件先归一到 UTC，DST 重叠时保留 fold；小时桶右端开，水位只能前进且迟到事件仍进入修订。
        - 使用者与工作流：导入随仓样例，逐模块复核，最后导出单一证据清单。

        ## 功能模块

        | 模块 | 使用者动作 | 入口 | 核心文件 | 测试 |
        |---|---|---|---|---|
        | M1 日志采信 | 运行样例并复核证据 | `/api/logs/import` / `/logs` | `app/modules/m1_logs/core.py` `app/modules/m1_logs/service.py` | `tests/test_m1_logs.py` |
| M2 时间解析 | 运行样例并复核证据 | `/api/time/normalize` / `/time` | `app/modules/m2_time/core.py` `app/modules/m2_time/service.py` | `tests/test_m2_time.py` |
| M3 事件去重 | 运行样例并复核证据 | `/api/events/dedupe` / `/events` | `app/modules/m3_events/core.py` `app/modules/m3_events/service.py` | `tests/test_m3_events.py` |
| M4 小时分桶 | 运行样例并复核证据 | `/api/buckets/rebuild` / `/buckets` | `app/modules/m4_buckets/core.py` `app/modules/m4_buckets/service.py` | `tests/test_m4_buckets.py` |
| M5 迟到修订 | 运行样例并复核证据 | `/api/watermark/advance` / `/watermark` | `app/modules/m5_watermark/core.py` `app/modules/m5_watermark/service.py` | `tests/test_m5_watermark.py` |
| M6 批次对账 | 运行样例并复核证据 | `/api/export/buckets.csv` / `/runs` | `app/modules/m6_runs/core.py` `app/modules/m6_runs/service.py` | `tests/test_m6_runs.py` |
| M7 合规撤回 | 在批次对账页办理撤回并核验差异 | `/api/runs/withdraw` `/api/runs/withdraw/resume` / `/runs` | `app/store.py` `app/privacy.py` `app/modules/m6_runs/handler.py` | `tests/test_m7_withdraw.py` `tests/test_m7_withdraw_api.py` |

        ## 陷阱登记

        | TRAP | 现象 | 朴素实现 | 本项目处理 | 处理位置 | 测试 |
        |---|---|---|---|---|---|
        | TRAP-03 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m1_logs/core.py` | `tests/test_m1_logs.py::test_trap_1` |
| TRAP-05 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m2_time/core.py` | `tests/test_m2_time.py::test_trap_1` |
| TRAP-07 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m3_events/core.py` | `tests/test_m3_events.py::test_trap_1` |
| TRAP-09 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m4_buckets/core.py` | `tests/test_m4_buckets.py::test_trap_1` |
| TRAP-11 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m5_watermark/core.py` | `tests/test_m5_watermark.py::test_trap_1` |
| TRAP-12 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m6_runs/core.py` | `tests/test_m6_runs.py::test_trap_1` |
| TRAP-13 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m1_logs/core.py` | `tests/test_m1_logs.py::test_trap_2` |
| TRAP-14 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m2_time/core.py` | `tests/test_m2_time.py::test_trap_2` |
| TRAP-16 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m3_events/core.py` | `tests/test_m3_events.py::test_trap_2` |
| TRAP-23 | 真实边界输入 | 朴素处理会错分 | 保留证据并稳定裁决 | `app/modules/m4_buckets/core.py` | `tests/test_m4_buckets.py::test_trap_2` |
| TRAP-30 | 撤回后迟到副本被再次采信 | 撤回只删当前行，迟到导入又复活 | 撤回即建墓碑，迟到副本命中匿名拦截不复活 | `app/store.py::import_ledger` | `tests/test_m7_withdraw.py::test_late_copy_after_withdraw_is_intercepted_not_revived` |
| TRAP-31 | 撤回需要保留原文导致泄露 | 留存请求原文/可读 ID 供核对 | 只存加盐 HMAC 指纹与脱敏标识，库文件无明文 | `app/privacy.py` `app/store.py` | `tests/test_m7_withdraw.py::test_import_persists_without_raw_identifier` |
| TRAP-32 | 撤回重算旧账改变封账凭证 | 撤回后重算已封账批次计数与差错率 | 封账数封存不可变，仅登记撤回影响标注 | `app/store.py::_annotate_sealed` | `tests/test_m7_withdraw.py::test_sealed_batch_numbers_immutable_withdraw_only_notes` |
| TRAP-33 | 撤回/重试重复扣减贡献 | 每次办理都再扣一次 | 幂等登记 + 中断续办按已扣贡献返回 | `app/store.py::withdraw` `app/store.py::resume_withdraw` | `tests/test_m7_withdraw.py::test_withdraw_is_idempotent_no_double_deduction` |
| TRAP-34 | 同名请求跨服务误删 | 仅按请求 ID 删除会波及其他服务 | 复合主键 `(服务, 指纹)` 隔离删除 | `app/store.py::withdraw` | `tests/test_m7_withdraw.py::test_same_request_id_other_service_not_deleted` |
| TRAP-35 | 撤回与导入并发竞态 | 先读后写导致撤回被迟到导入覆盖 | 单库 IMMEDIATE 事务串行化，撤回优先 | `app/store.py::import_ledger` `app/store.py::withdraw` | `tests/test_m7_withdraw.py::test_concurrent_import_and_withdraw_withdraw_wins` |

        ## 对账规则

        - 输入记录数 = 有效记录数 + 隔离记录数 + 空记录数。
        - 核心数值或事件数在转换、判定和导出之间保持守恒。
        - 同一输入摘要重跑复用原运行编号，不增加结果行。
        - 撤回只扣当前统计，不回改已封账批次；封账凭证的撤回影响以标注留痕，差异可按前后计数核验。
        - 撤回登记与拦截凭据均为匿名数据：不可逆指纹 + 脱敏标识 + 计数/差错率，不含原文与可读请求标识。

        ## 已知不覆盖

        - 生产系统连接、身份认证和外部密钥不在演示范围内。
