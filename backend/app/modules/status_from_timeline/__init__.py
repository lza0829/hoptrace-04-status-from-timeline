"""status_from_timeline — 状态只能由正式时间线末有效 hop 派生。

本模块是「映射 + 声明值 + 证明装载」的纯领域层：

* ``EVENT_STATUS`` 是 event_code → 对外状态 的唯一映射表。
* ``declared_status`` 读取运单行持有的 ``status_proj`` 列（不可变，仅由投影服务整体替换）。
* ``proof_row`` 把 (运单, 末 hop, 映射码, 投影值, 证明时刻, 时间线摘要) 组装成证明。
* ``insert_proof`` 只在投影事务内被调用，保证证明与投影同一时刻落库。

任何绕过本模块直接写 ``status_proj`` 的入口都会被投影服务拒绝；
见 ``app.services.projection`` 与 ``DirectStatusWriteError``。
"""

from __future__ import annotations

from typing import Any

from app.services.timeline import (
    last_effective_hop,
    list_primary,
    timeline_digest,
)

EVENT_STATUS: dict[str, str] = {
    "PICKED": "已揽收",
    "IN_TRANSIT": "运输中",
    "ARRIVED_HUB": "到站",
    "OUT_FOR_DELIVERY": "派送中",
    "DELIVERED": "已签收",
    "EXCEPTION": "异常",
}

UNKNOWN_STATUS = "未知"


def map_status(event_code: str | None) -> str:
    """event_code → 对外状态。未登记的码一律落到「未知」，不猜。"""
    if not event_code:
        return UNKNOWN_STATUS
    return EVENT_STATUS.get(event_code, UNKNOWN_STATUS)


def declared_status(conn, waybill_id: str) -> str:
    """读取运单行持有的持久投影值，运单不存在时抛 LookupError。"""
    row = conn.execute(
        "SELECT status_proj FROM waybills WHERE id=?", (waybill_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"运单不存在: {waybill_id}")
    return row["status_proj"]


def derive(conn, waybill_id: str) -> dict:
    """从正式时间线推导状态候选值（不写库）。

    返回结构供投影服务、证明接口、检查器共用：
    ``status`` / ``last_hop`` / ``mapped_code`` / ``timeline_digest``。
    """
    hops = list_primary(conn, waybill_id)
    last = last_effective_hop(hops)
    return {
        "status": map_status(last["event_code"] if last else None),
        "last_hop": last,
        "mapped_code": last["event_code"] if last else None,
        "timeline_digest": timeline_digest(hops),
        "hop_count": len(hops),
    }


def proof_row(conn, waybill_id: str, proj_value: str, created_at: str) -> dict:
    """组装一条待落库的状态证明（运单、末 hop、映射码、投影值、证明时刻）。"""
    derived = derive(conn, waybill_id)
    last = derived["last_hop"]
    return {
        "waybill_id": waybill_id,
        "last_hop_id": last["id"] if last else None,
        "mapped_code": derived["mapped_code"],
        "proj_value": proj_value,
        "timeline_digest": derived["timeline_digest"],
        "created_at": created_at,
    }


def insert_proof(conn, proof: dict) -> None:
    conn.execute(
        """
        INSERT INTO status_proofs(
          waybill_id, last_hop_id, mapped_code, proj_value, timeline_digest, created_at
        ) VALUES (?,?,?,?,?,?)
        """,
        (
            proof["waybill_id"],
            proof["last_hop_id"],
            proof["mapped_code"],
            proof["proj_value"],
            proof["timeline_digest"],
            proof["created_at"],
        ),
    )


def latest_proof(conn, waybill_id: str) -> dict | None:
    row = conn.execute(
        "SELECT * FROM status_proofs WHERE waybill_id=? ORDER BY id DESC LIMIT 1",
        (waybill_id,),
    ).fetchone()
    return dict(row) if row else None


def proof_matches(proof: dict | None, derived: dict) -> bool:
    """证明是否仍与当前正式时间线末 hop 一致。"""
    if proof is None:
        return False
    last = derived["last_hop"]
    return (
        proof["proj_value"] == derived["status"]
        and (proof["last_hop_id"] or None) == (last["id"] if last else None)
        and (proof["mapped_code"] or None) == derived["mapped_code"]
        and (proof["timeline_digest"] or None) == derived["timeline_digest"]
    )
