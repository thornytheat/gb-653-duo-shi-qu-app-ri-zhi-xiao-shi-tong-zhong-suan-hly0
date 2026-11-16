REASONS = {
    "BAD_COLUMNS": "字段数量不符", "EMPTY_VALUE": "必要值为空",
    "DUPLICATE_CONFLICT": "同一业务键取值冲突", "TRUNCATED": "尾记录不完整",
    "INVALID_VALUE": "值不符合定义", "STALE_VERSION": "提交版本已过期",
    "WITHDRAWN": "请求已撤回，迟到副本拦截不采信",
    "ALREADY_WITHDRAWN": "撤回登记已存在，按已扣贡献幂等返回",
    "WITHDRAW_RESUMED": "撤回曾中断，按已扣贡献续办未重复扣减",
    "NOT_FOUND": "当前台账与撤回登记中均无该指纹",
}

def reason(code: str) -> str:
    return REASONS.get(code, "未登记原因")
