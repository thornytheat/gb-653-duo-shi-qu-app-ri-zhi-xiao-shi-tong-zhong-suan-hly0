from __future__ import annotations
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from .privacy import anonymous_summary, masked_hint, request_fingerprint


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


class Store:
    def __init__(self, path: str, salt: str = "dev-withdraw-salt"):
        self.path = path
        self.salt = salt
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA foreign_keys=ON")
            db.execute(
                "CREATE TABLE IF NOT EXISTS runs "
                "(digest TEXT PRIMARY KEY, run_id TEXT NOT NULL, result TEXT NOT NULL)"
            )
            # 活台账：只存不可逆指纹，不存原文/可读请求标识。
            db.execute(
                "CREATE TABLE IF NOT EXISTS ledger_events ("
                "request_hash TEXT NOT NULL, service TEXT NOT NULL, "
                "hour TEXT NOT NULL, is_error INTEGER NOT NULL, "
                "withdrawn INTEGER NOT NULL DEFAULT 0, "
                "PRIMARY KEY (request_hash, service))"
            )
            # 撤回登记（墓碑）：不可逆拦截凭据 + 匿名汇总 + 前后差异。
            db.execute(
                "CREATE TABLE IF NOT EXISTS withdrawals ("
                "request_hash TEXT NOT NULL, service TEXT NOT NULL, "
                "masked_id TEXT NOT NULL, status TEXT NOT NULL, "
                "withdrawn_at TEXT NOT NULL, deducted_count INTEGER NOT NULL, "
                "deducted_errors INTEGER NOT NULL, before_count INTEGER NOT NULL, "
                "before_errors INTEGER NOT NULL, after_count INTEGER NOT NULL, "
                "after_errors INTEGER NOT NULL, before_error_rate REAL NOT NULL, "
                "after_error_rate REAL NOT NULL, reason TEXT NOT NULL, "
                "PRIMARY KEY (request_hash, service))"
            )
            # 迟到副本拦截凭据：匿名、无原文。
            db.execute(
                "CREATE TABLE IF NOT EXISTS interceptions ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, request_hash TEXT NOT NULL, "
                "service TEXT NOT NULL, source_line INTEGER, "
                "intercepted_at TEXT NOT NULL, reason TEXT NOT NULL)"
            )
            # 封账批次：计数与差错率封存后不可改。
            db.execute(
                "CREATE TABLE IF NOT EXISTS sealed_runs ("
                "run_id TEXT PRIMARY KEY, digest TEXT NOT NULL, sealed_at TEXT NOT NULL, "
                "count_total INTEGER NOT NULL, error_total INTEGER NOT NULL, "
                "error_rate REAL NOT NULL, csv TEXT NOT NULL, result TEXT NOT NULL)"
            )
            # 封账快照（匿名指纹级），用于核验撤回对封账批次的贡献。
            db.execute(
                "CREATE TABLE IF NOT EXISTS sealed_events ("
                "run_id TEXT NOT NULL, request_hash TEXT NOT NULL, service TEXT NOT NULL, "
                "hour TEXT NOT NULL, is_error INTEGER NOT NULL, "
                "PRIMARY KEY (run_id, request_hash, service))"
            )
            # 撤回对封账批次的影响标注：只注明、不改封存数。
            db.execute(
                "CREATE TABLE IF NOT EXISTS sealed_withdrawal_notes ("
                "run_id TEXT NOT NULL, request_hash TEXT NOT NULL, service TEXT NOT NULL, "
                "note TEXT NOT NULL, noted_at TEXT NOT NULL, "
                "PRIMARY KEY (run_id, request_hash, service))"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_ledger_service "
                "ON ledger_events(service, withdrawn)"
            )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_sealed_events_hash "
                "ON sealed_events(request_hash, service)"
            )

    def connect(self):
        return sqlite3.connect(self.path)

    # ---- M6 原有运行记录（保持向后兼容）----
    def record(self, digest: str, run_id: str, result: dict) -> dict:
        with self.connect() as db:
            db.execute("INSERT OR IGNORE INTO runs VALUES (?, ?, ?)",
                       (digest, run_id, json.dumps(result, ensure_ascii=False, sort_keys=True)))
            row = db.execute("SELECT run_id, result FROM runs WHERE digest=?", (digest,)).fetchone()
        return {"run_id": row[0], "result": json.loads(row[1])}

    def count(self) -> int:
        with self.connect() as db:
            return db.execute("SELECT COUNT(*) FROM runs").fetchone()[0]

    def all(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute("SELECT run_id, digest, result FROM runs ORDER BY run_id").fetchall()
        return [{"run_id": r[0], "digest": r[1], "result": json.loads(r[2])} for r in rows]

    # ---- M1 持久化导入：撤回优先，迟到副本拦截不复活 ----
    def import_ledger(self, parsed: list[dict], quarantine: list[dict]) -> dict:
        """在单个 IMMEDIATE 事务内导入，保证与撤回并发时以撤回为准。

        parsed 中每条至少含 service/request_id/status/source_line；任何明文 ID 不落库。
        """
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            accepted = duplicate = intercepted = 0
            for row in parsed:
                service = str(row.get("service", ""))
                rid = str(row.get("request_id", ""))
                h = request_fingerprint(service, rid, self.salt)
                tomb = db.execute(
                    "SELECT 1 FROM withdrawals WHERE request_hash=? AND service=?",
                    (h, service)).fetchone()
                if tomb:
                    # 撤回已生效：迟到副本一律拦截，绝不复活，仅留匿名凭据。
                    intercepted += 1
                    db.execute(
                        "INSERT INTO interceptions"
                        "(request_hash, service, source_line, intercepted_at, reason) "
                        "VALUES (?,?,?,?,?)",
                        (h, service, row.get("source_line"), _now(), "WITHDRAWN"))
                    continue
                cur = db.execute(
                    "INSERT OR IGNORE INTO ledger_events"
                    "(request_hash, service, hour, is_error, withdrawn) VALUES (?,?,?,?,0)",
                    (h, service, row["hour"], 1 if row["is_error"] else 0)).rowcount
                if cur:
                    accepted += 1
                else:
                    duplicate += 1
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return {
            "accepted": accepted,
            "duplicate": duplicate,
            "intercepted": intercepted,
            "quarantine_count": len(quarantine),
        }

    # ---- M7 撤回办理：幂等、可恢复、不重复扣减 ----
    def withdraw(self, service: str, request_id: str) -> dict:
        """撤回单个请求（按服务隔离）。返回不可逆凭据与匿名前后差异。"""
        service = str(service)
        h = request_fingerprint(service, str(request_id), self.salt)
        hint = masked_hint(service, str(request_id))
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT status, masked_id, withdrawn_at, deducted_count, deducted_errors, "
                "before_count, before_errors, after_count, after_errors, before_error_rate, "
                "after_error_rate, reason FROM withdrawals "
                "WHERE request_hash=? AND service=?", (h, service)).fetchone()
            if existing:
                # 幂等：已完成则原样返回；中断态则续办且不重复扣减。
                resumed = existing[0] != "DONE"
                reason = "WITHDRAW_RESUMED" if resumed else "ALREADY_WITHDRAWN"
                db.commit()
                return self._withdrawal_payload(h, service, hint, existing, reason, resumed)

            before_c = self._active_count(db, service)
            before_e = self._active_errors(db, service)
            before_rate = round(before_e / before_c, 6) if before_c else 0.0

            # 仅标记本服务本指纹；同名请求的其他服务行不受影响（复合主键隔离）。
            db.execute(
                "UPDATE ledger_events SET withdrawn=1 WHERE request_hash=? AND service=? "
                "AND withdrawn=0", (h, service))
            ded_rows = db.execute(
                "SELECT is_error FROM ledger_events WHERE request_hash=? AND service=?",
                (h, service)).fetchall()
            ded_count = len(ded_rows)
            ded_errors = sum(r[0] for r in ded_rows)

            after_c = self._active_count(db, service)
            after_e = self._active_errors(db, service)
            after_rate = round(after_e / after_c, 6) if after_c else 0.0

            db.execute(
                "INSERT INTO withdrawals (request_hash, service, masked_id, status, "
                "withdrawn_at, deducted_count, deducted_errors, before_count, before_errors, "
                "after_count, after_errors, before_error_rate, after_error_rate, reason) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (h, service, hint, "DONE", _now(), ded_count, ded_errors, before_c, before_e,
                 after_c, after_e, before_rate, after_rate, "WITHDRAWN"))
            self._annotate_sealed(db, h, service, ded_count, ded_errors)
            db.commit()
            row = db.execute(
                "SELECT status, masked_id, withdrawn_at, deducted_count, deducted_errors, "
                "before_count, before_errors, after_count, after_errors, before_error_rate, "
                "after_error_rate, reason FROM withdrawals "
                "WHERE request_hash=? AND service=?", (h, service)).fetchone()
            return self._withdrawal_payload(h, service, hint, row, "WITHDRAWN", False)
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def resume_withdraw(self, service: str, request_id: str) -> dict:
        """中断恢复入口：按已扣贡献续办，绝不重复扣减。

        已完成则幂等返回；中断态确认扣减已落账后仅把状态收敛为 DONE，不再扣第二次。
        """
        service = str(service)
        h = request_fingerprint(service, str(request_id), self.salt)
        hint = masked_hint(service, str(request_id))
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT status FROM withdrawals WHERE request_hash=? AND service=?",
                (h, service)).fetchone()
            if existing and existing[0] != "DONE":
                # 扣减在同一事务内落账，能看到登记即代表已扣；仅收敛状态，不重复扣减。
                db.execute(
                    "UPDATE withdrawals SET status='DONE' WHERE request_hash=? AND service=?",
                    (h, service))
                db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()
        return self.withdraw(service, request_id)

    def _withdrawal_payload(self, h, service, hint, row, reason, resumed):
        return {
            "status": row[0],
            "request_hash": h,
            "service": service,
            "masked_id": row[1],
            "withdrawn_at": row[2],
            "deducted": {"count": row[3], "errors": row[4]},
            "before": anonymous_summary(row[5], row[6]) | {"error_rate": row[9]},
            "after": anonymous_summary(row[7], row[8]) | {"error_rate": row[10]},
            "reason": reason,
            "resumed": resumed,
        }

    def _annotate_sealed(self, db, h, service, ded_count, ded_errors):
        """对包含该指纹的已封账批次登记撤回影响；封存计数一行不改。"""
        batches = db.execute(
            "SELECT run_id FROM sealed_events WHERE request_hash=? AND service=?",
            (h, service)).fetchall()
        for (run_id,) in batches:
            note = (f"撤回影响 {ded_count} 条 / 差错 {ded_errors} 条；"
                    "封账计数与差错率保持原值不改，仅标注")
            db.execute(
                "INSERT OR REPLACE INTO sealed_withdrawal_notes "
                "(run_id, request_hash, service, note, noted_at) VALUES (?,?,?,?,?)",
                (run_id, h, service, note, _now()))

    # ---- 封账：快照匿名指纹，封存数此后不可变 ----
    def seal(self, run_id: str, digest: str, rows: list[dict], csv: str, result: dict) -> dict:
        db = self.connect()
        try:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute(
                "SELECT run_id FROM sealed_runs WHERE run_id=?", (run_id,)).fetchone()
            if existing:
                db.commit()
                return {"run_id": run_id, "reused": True}
            count_total = sum(r["count"] for r in rows)
            error_total = sum(r["errors"] for r in rows)
            rate = round(error_total / count_total, 6) if count_total else 0.0
            db.execute(
                "INSERT INTO sealed_runs (run_id, digest, sealed_at, count_total, error_total, "
                "error_rate, csv, result) VALUES (?,?,?,?,?,?,?,?)",
                (run_id, digest, _now(), count_total, error_total, rate, csv,
                 json.dumps(result, ensure_ascii=False, sort_keys=True)))
            # 快照来自当前活台账（仅指纹级，无原文）。
            live = db.execute(
                "SELECT request_hash, service, hour, is_error FROM ledger_events "
                "WHERE withdrawn=0").fetchall()
            db.executemany(
                "INSERT OR IGNORE INTO sealed_events "
                "(run_id, request_hash, service, hour, is_error) VALUES (?,?,?,?,?)",
                [(run_id, r[0], r[1], r[2], r[3]) for r in live])
            db.commit()
            return {"run_id": run_id, "reused": False, "count_total": count_total,
                    "error_total": error_total, "error_rate": rate}
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    # ---- 查询：当前统计、封账批次、撤回/拦截凭据 ----
    @staticmethod
    def _active_count(db, service=None):
        if service is None:
            return db.execute(
                "SELECT COUNT(*) FROM ledger_events WHERE withdrawn=0").fetchone()[0]
        return db.execute(
            "SELECT COUNT(*) FROM ledger_events WHERE service=? AND withdrawn=0",
            (service,)).fetchone()[0]

    @staticmethod
    def _active_errors(db, service=None):
        if service is None:
            return db.execute(
                "SELECT COALESCE(SUM(is_error),0) FROM ledger_events WHERE withdrawn=0").fetchone()[0]
        return db.execute(
            "SELECT COALESCE(SUM(is_error),0) FROM ledger_events WHERE service=? AND withdrawn=0",
            (service,)).fetchone()[0]

    def live_summary(self) -> dict:
        with self.connect() as db:
            count = self._active_count(db)
            errors = self._active_errors(db)
            per_service = db.execute(
                "SELECT service, COUNT(*), COALESCE(SUM(is_error),0) FROM ledger_events "
                "WHERE withdrawn=0 GROUP BY service ORDER BY service").fetchall()
            withdrawn_total = db.execute(
                "SELECT COALESCE(SUM(deducted_count),0), COALESCE(SUM(deducted_errors),0) "
                "FROM withdrawals").fetchone()
        rate = round(errors / count, 6) if count else 0.0
        return {
            "active_count": count,
            "active_errors": errors,
            "error_rate": rate,
            "per_service": [
                {"service": s, "count": c, "errors": e,
                 "error_rate": round(e / c, 6) if c else 0.0}
                for s, c, e in per_service],
            "withdrawn_count": withdrawn_total[0],
            "withdrawn_errors": withdrawn_total[1],
        }

    def sealed_batches(self) -> list[dict]:
        with self.connect() as db:
            runs = db.execute(
                "SELECT run_id, digest, sealed_at, count_total, error_total, error_rate "
                "FROM sealed_runs ORDER BY sealed_at").fetchall()
            out = []
            for r in runs:
                notes = db.execute(
                    "SELECT request_hash, service, note, noted_at FROM sealed_withdrawal_notes "
                    "WHERE run_id=? ORDER BY noted_at", (r[0],)).fetchall()
                out.append({
                    "run_id": r[0], "digest": r[1], "sealed_at": r[2],
                    "count_total": r[3], "error_total": r[4], "error_rate": r[5],
                    "withdrawal_notes": [
                        {"request_hash": n[0], "service": n[1], "note": n[2], "noted_at": n[3]}
                        for n in notes],
                })
            return out

    def withdrawals(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT request_hash, service, masked_id, status, withdrawn_at, deducted_count, "
                "deducted_errors, before_count, before_errors, after_count, after_errors, "
                "before_error_rate, after_error_rate, reason "
                "FROM withdrawals ORDER BY withdrawn_at").fetchall()
        return [dict(zip([
            "request_hash", "service", "masked_id", "status", "withdrawn_at", "deducted_count",
            "deducted_errors", "before_count", "before_errors", "after_count", "after_errors",
            "before_error_rate", "after_error_rate", "reason"], r)) for r in rows]

    def interceptions(self) -> list[dict]:
        with self.connect() as db:
            rows = db.execute(
                "SELECT request_hash, service, source_line, intercepted_at, reason "
                "FROM interceptions ORDER BY id").fetchall()
        return [dict(zip(["request_hash", "service", "source_line", "intercepted_at", "reason"], r))
                for r in rows]
