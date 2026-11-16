"""M7 合规撤回：HTTP/页面层测试（容器 CI 经 TestClient 运行）。"""


def test_runs_page_renders_withdraw_panel(client):
    response = client.get("/runs")
    assert response.status_code == 200
    assert "办理撤回" in response.text
    assert "/api/runs/withdraw" in response.text
    assert "迟到副本拦截凭据" in response.text


def test_withdraw_api_full_lifecycle(client):
    text = "\n".join([
        '{"request_id":"r1","timestamp":"2026-11-15T01:05:00Z","service":"pay","status":200}',
        '{"request_id":"r2","timestamp":"2026-11-15T01:10:00Z","service":"pay","status":500}',
    ])
    imported = client.post("/api/logs/import", json={"text": text}).json()
    assert imported["accepted"] == 2

    w = client.post("/api/runs/withdraw", json={"service": "pay", "request_id": "r2"}).json()
    assert w["status"] == "DONE"
    assert w["deducted"] == {"count": 1, "errors": 1}
    assert "r2" not in str(w)  # 响应不含可读 ID

    # 幂等：不重复扣减
    w2 = client.post("/api/runs/withdraw", json={"service": "pay", "request_id": "r2"}).json()
    assert w2["reason"] == "ALREADY_WITHDRAWN"

    runs = client.get("/api/runs").json()
    assert runs["live"]["active_count"] == 1
    assert runs["live"]["withdrawn_count"] == 1
    assert runs["withdrawals"][0]["masked_id"].startswith("pay:")

    # 迟到副本被拦截
    late = client.post(
        "/api/logs/import",
        json={"text": '{"request_id":"r2","timestamp":"2026-11-15T09:00:00Z","service":"pay","status":200}'}).json()
    assert late["intercepted"] == 1
    assert client.get("/api/runs").json()["interceptions"][0]["reason"] == "WITHDRAWN"


def test_withdraw_requires_service_and_id(client):
    resp = client.post("/api/runs/withdraw", json={"service": "pay"})
    assert resp.status_code == 422
    assert resp.json()["error"] == "EMPTY_VALUE"


def test_sealed_batch_annotated_not_mutated(client):
    client.post("/api/logs/import", json={"text": '{"request_id":"r1","timestamp":"2026-11-15T01:05:00Z","service":"pay","status":500}'})
    client.get("/api/export/buckets.csv")  # 封账
    before = client.get("/api/runs").json()["sealed_batches"][0]
    client.post("/api/runs/withdraw", json={"service": "pay", "request_id": "r1"})
    after = client.get("/api/runs").json()["sealed_batches"][0]
    assert after["count_total"] == before["count_total"] == 1
    assert after["error_total"] == before["error_total"] == 1
    assert len(after["withdrawal_notes"]) == 1


def test_resume_endpoint_does_not_double_deduct(client):
    client.post("/api/logs/import", json={"text": '{"request_id":"r1","timestamp":"2026-11-15T01:05:00Z","service":"pay","status":200}'})
    client.post("/api/runs/withdraw", json={"service": "pay", "request_id": "r1"})
    resumed = client.post("/api/runs/withdraw/resume",
                          json={"service": "pay", "request_id": "r1"}).json()
    assert resumed["status"] == "DONE"
    assert client.get("/api/runs").json()["live"]["withdrawn_count"] == 1
