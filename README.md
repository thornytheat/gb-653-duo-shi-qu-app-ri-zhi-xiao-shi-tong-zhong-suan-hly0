# 多时区应用日志小时桶重算

        面向一线复核人员的单服务数据工作台。样例数据随仓库提供，结论保留行号、原因码和原值。

        ## 业务模块

        - M1 日志采信：`/api/logs/import`
- M2 时间解析：`/api/time/normalize`
- M3 事件去重：`/api/events/dedupe`
- M4 小时分桶：`/api/buckets/rebuild`
- M5 迟到修订：`/api/watermark/advance`
- M6 批次对账：`/api/export/buckets.csv`
- M7 合规撤回：`/api/runs/withdraw`（在批次对账页办理，`/api/runs/withdraw/resume` 中断续办）

        ## 核心规则

        事件先归一到 UTC，DST 重叠时保留 fold；小时桶右端开，水位只能前进且迟到事件仍进入修订。

        ## 合规撤回规则

        - 撤回后该服务该请求的原文与可读标识不再保留，仅存加盐 HMAC 不可逆指纹、脱敏标识与匿名汇总。
        - 当前统计实时扣除撤回贡献（计数与差错率）；已封账批次的计数与差错率封存不改，只登记撤回影响标注。
        - 撤回与导入并发时以撤回为准（单库 IMMEDIATE 事务串行化）；迟到副本命中墓碑即拦截，不复活，仅留匿名拦截凭据。
        - 撤回按 `(服务, 指纹)` 隔离，同名请求的其他服务不误删；办理幂等，中断可恢复，续办按已扣贡献续办不重复扣减。
        - 指纹盐经 `WITHDRAW_SALT` 环境变量注入，生产必须覆盖默认演示值。

        ## 启动

        ```bash
        docker compose up --build
        ```

        浏览器访问 `http://localhost:18212`。运行测试：

        ```bash
        docker compose exec -T app pytest -q
        ```

        ## 样例流程

        依次运行六个模块；最后在批次页复核输入、有效、隔离与输出合计。同一输入摘要重复执行时复用原 `run_id`。

        ## 已知不覆盖

        不处理加密文件与需要外部密钥的对象；不连接真实生产存储。
