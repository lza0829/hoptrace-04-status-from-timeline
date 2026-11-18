"""装载批次。

每一条写入正式时间线的 hop 成功后，都在**同一事务**内调用投影服务重算
``status_proj`` 并追加状态证明；批次结束统一提交。

因此装载后投影一定跟随正式线末有效 hop，任何一步失败整批回滚，
不会出现「正式线已变、投影仍是旧值」的分叉。
"""

import json
import uuid
from datetime import datetime, timezone

from app.db import FIXTURES_DIR, connect
from app.services import projection
from app.services import timeline as timeline_svc


def run_batch() -> dict:
    path = FIXTURES_DIR / "ingest_batch.json"
    if not path.exists():
        return {"ok": False, "error": "缺少 ingest_batch.json"}
    payload = json.loads(path.read_text(encoding="utf-8"))
    batch_id = payload.get("batch_id") or f"B-{uuid.uuid4().hex[:8]}"
    cutoff = payload.get("cutoff_ts")
    hops = payload.get("hops", [])

    conn = connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        written = 0
        redrawn: set[str] = set()
        for hop in hops:
            wid = hop["waybill_id"]
            exists = conn.execute("SELECT 1 FROM waybills WHERE id=?", (wid,)).fetchone()
            if not exists:
                conn.execute(
                    "INSERT INTO waybills(id, title, status_proj, created_at) VALUES (?,?,?,?)",
                    (wid, hop.get("waybill_title") or wid, "未知", _now()),
                )
            outcome = projection.load_hop(conn, hop)
            if outcome["written"]:
                written += 1
                redrawn.add(wid)
        report = {
            "batch_id": batch_id,
            "cutoff_ts": cutoff,
            "written": written,
            "input": len(hops),
            "projection_redrawn": sorted(redrawn),
        }
        conn.execute(
            "INSERT OR REPLACE INTO ingest_batches(id, cutoff_ts, created_at, report_json) VALUES (?,?,?,?)",
            (batch_id, cutoff, _now(), json.dumps(report, ensure_ascii=False)),
        )
        conn.commit()
        return {"ok": True, "report": report}
    except Exception as e:
        conn.rollback()
        return {"ok": False, "error": str(e)}
    finally:
        conn.close()


def _now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
