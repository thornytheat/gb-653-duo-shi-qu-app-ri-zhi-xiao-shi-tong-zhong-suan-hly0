from fastapi import APIRouter, Body, Request
from fastapi.responses import Response
from .service import execute, page_data, withdraw_request, resume_request
from app.errors import DomainError
router = APIRouter(tags=["M6-批次对账"])

@router.get("/runs")
def page(request: Request):
    data = page_data(request.app.state.store)
    return request.app.state.templates.TemplateResponse(request, "m6_runs.html", {"title": "批次对账", "data": data})

@router.get("/api/runs")
def runs(request: Request):
    execute({"store": request.app.state.store})
    store = request.app.state.store
    return {"runs": store.all(),
            "live": store.live_summary(),
            "sealed_batches": store.sealed_batches(),
            "withdrawals": store.withdrawals(),
            "interceptions": store.interceptions()}

@router.get("/api/export/buckets.csv")
def export(request: Request):
    data = execute({"store": request.app.state.store})
    return Response(data["csv"], media_type="text/csv", headers={"Content-Disposition": "attachment; filename=evidence.csv"})

def _require(payload: dict, key: str):
    value = payload.get(key)
    if not value or not str(value).strip():
        raise DomainError("EMPTY_VALUE", f"必要值为空: {key}")
    return str(value).strip()

@router.post("/api/runs/withdraw")
def withdraw(request: Request, payload: dict = Body(default={})):
    """在批次对账页办理撤回：当前统计扣贡献，封账只标注不改数，幂等可恢复。"""
    service = _require(payload, "service")
    request_id = _require(payload, "request_id")
    return withdraw_request(request.app.state.store, service, request_id)

@router.post("/api/runs/withdraw/resume")
def resume(request: Request, payload: dict = Body(default={})):
    """中断恢复：按已扣贡献续办，不重复扣减。"""
    service = _require(payload, "service")
    request_id = _require(payload, "request_id")
    return resume_request(request.app.state.store, service, request_id)
