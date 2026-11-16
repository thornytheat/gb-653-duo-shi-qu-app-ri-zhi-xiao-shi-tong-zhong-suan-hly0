"""M7 合规撤回：核心存储与规则测试（仅依赖标准库与项目模块）。"""
import json
import os

import pytest

from app.store import Store
from app.privacy import request_fingerprint, masked_hint
from app.modules.m1_logs.core import run as m1_run
from app.modules.m6_runs.core import run as m6_run

PAY = '{"request_id":"r1","timestamp":"2026-11-15T01:05:00Z","service":"pay","status":200}'
PAY_ERR = '{"request_id":"r2","timestamp":"2026-11-15T01:10:00Z","service":"pay","status":500}'
PAY_3 = '{"request_id":"r3","timestamp":"2026-11-15T02:05:00Z","service":"pay","status":200}'
SEARCH_R1 = '{"request_id":"r1","timestamp":"2026-11-15T01:05:00Z","service":"search","status":200}'


@pytest.fixture
def store(tmp_path):
    return Store(str(tmp_path / "m7.db"), salt="unit-salt")


def _import(store, *lines):
    return m1_run({"text": "\n".join(lines), "store": store})


def test_import_persists_without_raw_identifier(store):
    out = _import(store, PAY, PAY_ERR)
    assert out["accepted"] == 2 and out["intercepted"] == 0
    raw = open(store.path, "rb").read()
    # 原文与可读请求标识一律不入库
    for token in (b"r1", b"r2", b"request_id", b"status"):
        assert token not in raw


def test_withdraw_deducts_current_contribution_and_keeps_anonymous_diff(store):
    _import(store, PAY, PAY_ERR, PAY_3)
    w = store.withdraw("pay", "r2")
    assert w["status"] == "DONE"
    assert w["deducted"] == {"count": 1, "errors": 1}
    # 服务级前后差异可核查
    assert w["before"]["active_count"] == 3 and w["before"]["error_count"] == 1
    assert w["after"]["active_count"] == 2 and w["after"]["error_count"] == 0
    assert w["masked_id"] == masked_hint("pay", "r2")
    assert w["request_hash"] == request_fingerprint("pay", "r2", "unit-salt")
    # 当前统计已扣除贡献
    live = store.live_summary()
    assert live["active_count"] == 2 and live["active_errors"] == 0
    assert live["withdrawn_count"] == 1 and live["withdrawn_errors"] == 1


def test_withdraw_never_returns_readable_id(store):
    _import(store, PAY)
    payload = json.dumps(store.withdraw("pay", "r1"), ensure_ascii=False)
    assert "r1" not in payload


def test_withdraw_is_idempotent_no_double_deduction(store):
    _import(store, PAY, PAY_ERR, PAY_3)
    first = store.withdraw("pay", "r2")
    second = store.withdraw("pay", "r2")
    assert second["reason"] == "ALREADY_WITHDRAWN"
    assert second["deducted"] == first["deducted"] == {"count": 1, "errors": 1}
    assert store.live_summary()["withdrawn_count"] == 1
    assert len(store.withdrawals()) == 1


def test_resume_after_interruption_does_not_deduct_twice(store):
    _import(store, PAY_ERR)
    store.withdraw("pay", "r2")
    with store.connect() as db:
        db.execute("UPDATE withdrawals SET status='INTERRUPTED' WHERE service='pay'")
        db.commit()
    before = store.live_summary()
    resumed = store.resume_withdraw("pay", "r2")
    after = store.live_summary()
    assert resumed["status"] == "DONE"
    assert resumed["deducted"] == {"count": 1, "errors": 1}
    assert before == after  # 续办未再次扣减
    assert after["withdrawn_count"] == 1


def test_late_copy_after_withdraw_is_intercepted_not_revived(store):
    _import(store, PAY)
    store.withdraw("pay", "r1")
    late = '{"request_id":"r1","timestamp":"2026-11-15T09:00:00Z","service":"pay","status":200}'
    out = _import(store, late)
    assert out["intercepted"] == 1 and out["accepted"] == 0
    live = store.live_summary()
    assert live["active_count"] == 0
    intercepts = store.interceptions()
    assert len(intercepts) == 1 and intercepts[0]["reason"] == "WITHDRAWN"
    assert intercepts[0]["request_hash"] == request_fingerprint("pay", "r1", "unit-salt")
    # 拦截凭据无原文
    assert "r1" not in json.dumps(intercepts)


def test_same_request_id_other_service_not_deleted(store):
    _import(store, PAY, SEARCH_R1)
    store.withdraw("pay", "r1")
    live = store.live_summary()
    assert live["active_count"] == 1
    services = {x["service"]: x for x in live["per_service"]}
    assert "pay" not in services
    assert services["search"]["count"] == 1
    # search 侧同名请求之后仍可正常导入（未被误设墓碑）
    again = _import(store, '{"request_id":"r9","timestamp":"2026-11-15T03:00:00Z","service":"search","status":200}')
    assert again["accepted"] == 1


def test_sealed_batch_numbers_immutable_withdraw_only_notes(store):
    _import(store, PAY, PAY_ERR, PAY_3)
    sealed = m6_run({"store": store})
    assert sealed["input_count"] == 3 and sealed["errors"] == 1
    batch_before = store.sealed_batches()[0]
    # 封账后撤回其中一条
    store.withdraw("pay", "r2")
    batch_after = store.sealed_batches()[0]
    assert batch_after["count_total"] == batch_before["count_total"] == 3
    assert batch_after["error_total"] == batch_before["error_total"] == 1
    assert batch_after["error_rate"] == batch_before["error_rate"]
    assert len(batch_after["withdrawal_notes"]) == 1
    assert "不改" in batch_after["withdrawal_notes"][0]["note"]
    # 当前统计已扣，封账数不变
    assert store.live_summary()["active_count"] == 2


def test_reseal_same_input_reuses_run_id(store):
    _import(store, PAY, PAY_3)
    first = m6_run({"store": store})
    second = m6_run({"store": store})
    assert second["run_id"] == first["run_id"] and second["reused"] is True


def test_withdraw_changes_current_error_rate_but_not_sealed(store):
    _import(store, PAY, PAY_ERR)
    sealed = m6_run({"store": store})
    sealed_rate = store.sealed_batches()[0]["error_rate"]
    store.withdraw("pay", "r2")  # 撤回唯一差错
    assert store.live_summary()["error_rate"] == 0.0
    assert store.sealed_batches()[0]["error_rate"] == sealed_rate == 0.5


def test_withdraw_unknown_fingerprint_records_tombstone_with_zero_deduction(store):
    w = store.withdraw("pay", "ghost")
    assert w["deducted"] == {"count": 0, "errors": 0}
    # 墓碑已建立：后续迟到副本被拦截
    out = _import(store, '{"request_id":"ghost","timestamp":"2026-11-15T03:00:00Z","service":"pay","status":200}')
    assert out["intercepted"] == 1


def test_concurrent_import_and_withdraw_withdraw_wins(store):
    import threading

    barrier = threading.Barrier(2)
    result = {}

    def do_import():
        barrier.wait()
        result["import"] = _import(
            store, '{"request_id":"x","timestamp":"2026-11-15T02:00:00Z","service":"pay","status":200}')

    def do_withdraw():
        barrier.wait()
        result["withdraw"] = store.withdraw("pay", "x")

    t1 = threading.Thread(target=do_import)
    t2 = threading.Thread(target=do_withdraw)
    t1.start(); t2.start(); t1.join(); t2.join()

    assert len(store.withdrawals()) == 1  # 墓碑必然建立
    assert store.live_summary()["active_count"] == 0  # 撤回优先，x 不存活
    imp = result["import"]["ledger"] if "ledger" in result["import"] else result["import"]
    assert imp["accepted"] + imp["intercepted"] == 1


def test_quarantine_still_works_alongside_persistence(store):
    text = '{"request_id":"a","timestamp":"2026-11-15T01:00:00Z","service":"pay","status":200}\n{"request_id":'
    out = m1_run({"text": text, "store": store})
    assert out["quarantine_count"] == 1 and out["accepted"] == 1
    assert out["ledger"]["quarantine_count"] == 1
