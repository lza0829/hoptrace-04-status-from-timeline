"""正式时间线物化。

正式时间线只包含 primary 通道且未被撤回的 hop，按 (event_ts, id) 升序物化。
本模块只负责「哪些 hop 构成正式线」以及时间线摘要，不负责状态映射。

状态投影见 ``app.modules.status_from_timeline`` / ``app.services.projection``。
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Iterable, Sequence


HOP_COLUMNS = (
    "id",
    "waybill_id",
    "event_ts",
    "location_code",
    "event_code",
    "seq",
    "channel",
    "retracted",
)


def list_primary(conn, waybill_id: str) -> list[dict]:
    """物化一条运单的正式时间线（只读）。"""
    rows = conn.execute(
        """
        SELECT id, waybill_id, event_ts, location_code, event_code, seq, channel, retracted
        FROM hops
        WHERE waybill_id=? AND channel='primary' AND retracted=0
        ORDER BY event_ts ASC, id ASC
        """,
        (waybill_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def last_effective_hop(hops: Sequence[dict]) -> dict | None:
    """正式时间线中的末有效 hop。

    正式线已经按 (event_ts, id) 升序物化，末元素即末有效 hop。
    这里仍用显式 max 做一次防御，避免调用方传入未排序序列。
    """
    if not hops:
        return None
    return max(hops, key=lambda h: (h.get("event_ts") or "", h.get("id") or ""))


def timeline_digest(hops: Sequence[dict]) -> str:
    """对正式时间线做稳定摘要，作为状态证明的一部分。

    摘要覆盖所有正式 hop 的身份、时刻、地点、事件码与 seq；
    任何一次成功的正式线变更都会改变摘要，从而可核对证明是否仍对应当前时间线。
    """
    payload = [
        [
            h.get("id"),
            h.get("event_ts"),
            h.get("location_code"),
            h.get("event_code"),
            h.get("seq"),
        ]
        for h in hops
    ]
    raw = json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def materialize(conn, waybill_id: str) -> dict:
    """返回正式时间线的完整物化结果（只读，供接口/检查器共用）。"""
    hops = list_primary(conn, waybill_id)
    return {
        "waybill_id": waybill_id,
        "hops": hops,
        "hop_count": len(hops),
        "last_effective_hop": last_effective_hop(hops),
        "timeline_digest": timeline_digest(hops),
    }


def append_primary(conn, hop: dict) -> bool:
    """把一条 hop 写入正式时间线。

    只允许写 primary 通道；重复 hop 由唯一键幂等忽略。
    返回 True 表示正式线确实发生了变更。
    """
    required = ("id", "waybill_id", "event_ts", "location_code", "event_code")
    missing = [k for k in required if not hop.get(k)]
    if missing:
        raise ValueError(f"hop 缺少必填字段: {', '.join(missing)}")

    conn.execute(
        """
        INSERT OR IGNORE INTO hops(id, waybill_id, event_ts, location_code, event_code, seq, channel)
        VALUES (?,?,?,?,?,?, 'primary')
        """,
        (
            hop["id"],
            hop["waybill_id"],
            hop["event_ts"],
            hop["location_code"],
            hop["event_code"],
            hop.get("seq"),
        ),
    )
    return conn.execute("SELECT changes() AS c").fetchone()["c"] > 0
