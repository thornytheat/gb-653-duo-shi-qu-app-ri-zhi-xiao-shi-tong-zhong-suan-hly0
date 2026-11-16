import csv, io
from app.manifest import canonical_digest, run_id
SAMPLE={"store":None,"rows":[{"hour":"2026-11-15T01:00:00Z","service":"pay","count":2,"errors":1},{"hour":"2026-11-15T02:00:00Z","service":"pay","count":1,"errors":0}]}
def csv_text(rows):
    out=io.StringIO(); w=csv.DictWriter(out,fieldnames=["hour","service","count","errors"],lineterminator="\n"); w.writeheader(); w.writerows(rows); return out.getvalue()

def _live_rows(store):
    """按 (小时,服务) 汇总当前未撤回事件，作为封账输入。"""
    with store.connect() as db:
        agg=db.execute(
            "SELECT hour, service, COUNT(*) AS count, COALESCE(SUM(is_error),0) AS errors "
            "FROM ledger_events WHERE withdrawn=0 GROUP BY hour, service "
            "ORDER BY hour, service").fetchall()
    return [{"hour":h,"service":s,"count":c,"errors":e} for h,s,c,e in agg]

def run(payload):
    store=payload.get("store")
    if store is not None and hasattr(store,"seal"):
        rows=_live_rows(store)
        digest=canonical_digest(rows); rid=run_id(rows)
        result={"input_count":sum(x["count"] for x in rows),
                "valid_count":sum(x["count"] for x in rows),
                "quarantine_count":0,
                "errors":sum(x["errors"] for x in rows)}
        rid=store.record(digest,rid,result)["run_id"]
        sealed=store.seal(rid,digest,rows,csv_text(rows),result)
        return {"status":"SEALED","run_id":rid,"digest":digest,"csv":csv_text(rows),
                "reused":sealed.get("reused",False),**result,"reason":"OK"}
    rows=payload.get("rows",SAMPLE["rows"]); digest=canonical_digest(rows); rid=run_id(rows); result={"input_count":sum(x["count"] for x in rows),"valid_count":sum(x["count"] for x in rows),"quarantine_count":0,"errors":sum(x["errors"] for x in rows)}
    if store: rid=store.record(digest,rid,result)["run_id"]
    return {"status":"READY","run_id":rid,"digest":digest,"csv":csv_text(rows),**result,"reason":"OK"}
