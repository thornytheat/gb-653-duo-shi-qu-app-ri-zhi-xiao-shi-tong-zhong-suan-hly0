import json
SAMPLE={"text":'{"request_id":"9007199254740993","timestamp":"2026-11-15T01:05:00Z","service":"pay","status":200}\n{"request_id":"r2","timestamp":"2026-11-15T09:10:00+08:00","service":"pay","status":500}\n{"request_id":"r3"'}
def parse(text):
    rows=[]; quarantine=[]
    for line_no,line in enumerate(text.splitlines(),1):
        if not line.strip(): continue
        try:
            row=json.loads(line); row["request_id"]=str(row.get("request_id","")); row["source_line"]=line_no; rows.append(row)
        except json.JSONDecodeError: quarantine.append({"source_line":line_no,"reason":"TRUNCATED","raw":line})
    return {"rows":rows,"quarantine":quarantine}

def _hour_key(value):
    from datetime import datetime
    dt=datetime.fromisoformat(value.replace("Z","+00:00"))
    return dt.strftime("%Y-%m-%dT%H:00:00Z")

def _enrich(rows):
    """补出 UTC 小时桶与差错标记，供持久化；不改变原始行内容。"""
    out=[]
    for row in rows:
        out.append({**row, "hour": _hour_key(row["timestamp"]),
                    "is_error": int(int(row.get("status", 0)) >= 500)})
    return out

def run(payload):
    text=payload.get("text",SAMPLE["text"])
    out=parse(text)
    result={"status":"READY","input_count":len(out["rows"])+len(out["quarantine"]),"valid_count":len(out["rows"]),"quarantine_count":len(out["quarantine"]),"first_id":out["rows"][0]["request_id"] if out["rows"] else "","reason":out["quarantine"][0]["reason"] if out["quarantine"] else "OK"}
    store=payload.get("store")
    if store is not None and hasattr(store,"import_ledger"):
        # 持久化路径：原文与可读 ID 不落库；命中撤回墓碑的迟到副本被拦截不复活。
        ledger=store.import_ledger(_enrich(out["rows"]), out["quarantine"])
        result.update({"ledger":ledger,
                       "accepted":ledger["accepted"],"duplicate":ledger["duplicate"],
                       "intercepted":ledger["intercepted"]})
        result["reason"]="WITHDRAWN" if ledger["intercepted"] else result["reason"]
    return result
