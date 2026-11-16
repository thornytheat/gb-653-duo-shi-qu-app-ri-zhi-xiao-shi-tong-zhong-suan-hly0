from . import core


def execute(payload: dict | None = None) -> dict:
    return core.run(payload or core.SAMPLE)


def page_data(store) -> dict:
    """批次对账页数据：当前统计（已扣撤回贡献）+ 封账批次 + 撤回/拦截凭据。"""
    sealed = core.run({"store": store})
    return {
        "status": sealed["status"],
        "run_id": sealed["run_id"],
        "live": store.live_summary(),
        "sealed_batches": store.sealed_batches(),
        "withdrawals": store.withdrawals(),
        "interceptions": store.interceptions(),
        "csv": sealed["csv"],
    }


def withdraw_request(store, service: str, request_id: str) -> dict:
    return store.withdraw(service, request_id)


def resume_request(store, service: str, request_id: str) -> dict:
    return store.resume_withdraw(service, request_id)
