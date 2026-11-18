"""状态投影同源验收：直接改投影必须失败；装载后投影随末 hop 变。"""

import os
import tempfile
from pathlib import Path

import pytest

_SANDBOX = Path(tempfile.mkdtemp(prefix="hoptrace-test-"))
os.environ["DATA_DIR"] = str(_SANDBOX / "data")
os.environ["FIXTURES_DIR"] = str(Path(__file__).resolve().parents[2] / "fixtures")

from fastapi.testclient import TestClient  # noqa: E402

from app import seed  # noqa: E402
from app.db import DB_PATH, connect  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    DB_PATH.unlink(missing_ok=True)
    seed.init_db()
    with TestClient(app) as c:
        yield c


def _wb(client, wid):
    return next(w for w in client.get("/api/waybills").json() if w["id"] == wid)


def test_direct_status_write_fails_whole(client):
    before = _wb(client, "WB-1001")
    r = client.post("/api/waybills/WB-1001/status", json={"status_proj": "已签收"})
    assert r.status_code == 409
    body = r.json()["detail"]
    assert body["error"] == "DIRECT_STATUS_WRITE_REJECTED"
    assert body["rolled_back"] is True
    assert body["reason"]
    assert _wb(client, "WB-1001")["status_proj"] == before["status_proj"]
    assert client.get("/api/status-check").json()["diverged"] == 0


def test_raw_update_rejected_by_db_guard(client):
    conn = connect()
    try:
        with pytest.raises(Exception):
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE waybills SET status_proj='已签收' WHERE id='WB-1002'")
            conn.commit()
    finally:
        conn.rollback()
        conn.close()
    assert _wb(client, "WB-1002")["status_proj"] == "已揽收"


def test_raw_update_rejected_even_when_value_matches(client):
    """裸 UPDATE 即使凑巧等于映射值也必须失败：必须经投影服务。"""
    conn = connect()
    try:
        with pytest.raises(Exception):
            conn.execute("BEGIN IMMEDIATE")
            conn.execute("UPDATE waybills SET status_proj='已揽收' WHERE id='WB-1002'")
            conn.commit()
    finally:
        conn.rollback()
        conn.close()
    assert _wb(client, "WB-1002")["status_proj"] == "已揽收"
    conn = connect()
    try:
        assert conn.execute("SELECT COUNT(*) AS c FROM projection_write_tokens").fetchone()["c"] == 0
    finally:
        conn.close()


def test_projection_follows_last_effective_hop_after_load(client):
    assert _wb(client, "WB-1002")["status_proj"] == "已揽收"
    r = client.post(
        "/api/waybills/WB-1002/hops",
        json={
            "id": "H-NEW",
            "event_ts": "2026-11-17T15:00:00Z",
            "location_code": "SH-LOCAL",
            "event_code": "DELIVERED",
            "seq": 9,
        },
    )
    assert r.status_code == 200 and r.json()["written"] is True
    assert _wb(client, "WB-1002")["status_proj"] == "已签收"

    proof = client.get("/api/waybills/WB-1002/status-proof").json()
    assert proof["last_hop"]["id"] == "H-NEW"
    assert proof["mapped_code"] == "DELIVERED"
    assert proof["proj_value"] == "已签收"
    assert proof["proof_at"]
    assert proof["同源"] is True
    check = client.get("/api/status-check").json()
    assert check["diverged"] == 0
    assert check["aligned"] == check["checked"]


def test_out_of_order_hop_keeps_projection_and_refreshes_digest(client):
    before = client.get("/api/waybills/WB-1002/status-proof").json()
    r = client.post(
        "/api/waybills/WB-1002/hops",
        json={
            "id": "H-OLD",
            "event_ts": "2026-11-17T08:00:00Z",
            "location_code": "SH-OLD",
            "event_code": "EXCEPTION",
            "seq": 0,
        },
    )
    assert r.status_code == 200
    after = client.get("/api/waybills/WB-1002/status-proof").json()
    assert after["proj_value"] == before["proj_value"]
    assert after["last_hop"]["id"] == before["last_hop"]["id"]
    assert after["timeline_digest"] != before["timeline_digest"]
    assert after["同源"] is True


def test_ingest_batch_updates_projection(client):
    r = client.post("/api/ingest/run")
    assert r.json()["ok"] is True
    wb = _wb(client, "WB-1001")
    assert wb["status_proj"] == "派送中"
    assert client.get("/api/status-check").json()["diverged"] == 0
    assert client.get("/api/overview").json()["projection_diverged"] == 0


def test_replay_does_not_append_duplicate_proofs(client):
    first = client.post("/api/ingest/run").json()
    assert first["ok"] and first["report"]["written"] == 2
    n1 = len(client.get("/api/status-proofs").json())
    second = client.post("/api/ingest/run").json()
    assert second["report"]["written"] == 0
    assert second["report"]["projection_redrawn"] == []
    assert len(client.get("/api/status-proofs").json()) == n1
    assert client.get("/api/status-check").json()["diverged"] == 0


def test_partial_ingest_failure_rolls_back_timeline_and_projection(client, tmp_path, monkeypatch):
    """批次中途失败：正式 hop 与投影一起回滚，不留下半成功。"""
    from app.services import ingest as ingest_svc

    before = _wb(client, "WB-1001")["status_proj"]
    before_hops = client.get("/api/waybills/WB-1001/timeline").json()["hops"]
    (tmp_path / "ingest_batch.json").write_text(
        '{"batch_id":"B-BAD","hops":['
        '{"id":"H-OK","waybill_id":"WB-1001","event_ts":"2026-11-17T22:00:00Z",'
        '"location_code":"X","event_code":"DELIVERED"},'
        '{"id":"H-BAD","waybill_id":"WB-1001","event_ts":"2026-11-17T23:00:00Z",'
        '"location_code":"Y"}]}',
        encoding="utf-8",
    )
    monkeypatch.setattr(ingest_svc, "FIXTURES_DIR", tmp_path)
    result = client.post("/api/ingest/run").json()

    assert result["ok"] is False and "event_code" in result["error"]
    after = client.get("/api/waybills/WB-1001/timeline").json()
    assert after["hops"] == before_hops
    assert _wb(client, "WB-1001")["status_proj"] == before
    assert client.get("/api/status-check").json()["diverged"] == 0


def test_checker_reports_divergence_instead_of_rubber_stamping(client):
    """检查器独立重算：即便绕过保护写坏了数据，也必须报出分叉。"""
    conn = connect()
    try:
        conn.execute("DROP TRIGGER waybills_status_proj_guard")
        conn.execute("UPDATE waybills SET status_proj='已签收' WHERE id='WB-1002'")
        conn.commit()
    finally:
        conn.close()

    check = client.get("/api/status-check").json()
    row = next(i for i in check["items"] if i["waybill_id"] == "WB-1002")
    assert row["同源"] is False
    assert row["status_proj"] == "已签收"
    assert row["expected_status"] == "已揽收"
    assert check["diverged"] == 1
    assert client.get("/api/overview").json()["projection_diverged"] == 1
