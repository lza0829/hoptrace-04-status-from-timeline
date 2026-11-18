"""状态投影服务。

落库形态（择一，本实现选 **运单行持有不可变 status_proj 列**）：
``waybills.status_proj`` 是唯一的对外可读状态，只能由 ``refresh`` /
``apply_timeline_change`` 在「正式时间线成功变更」的同一事务内整体替换。

派生路径（择一，本实现选 **时间线每次成功变更时同事务重算**）：
1. 正式线写入 hop（``timeline.append_primary``）成功；
2. 在同一事务内重算末有效 hop → 映射 → 整体替换 status_proj；
3. 同一事务内追加一条状态证明。
任一步失败整体回滚，因此不存在「投影已变而正式线未变」或反过来的分叉。

直接改投影的入口（``set_direct`` / 裸 UPDATE status_proj）一律整笔失败：
抛 ``DirectStatusWriteError``，事务回滚，不留下半成功。
"""

from __future__ import annotations

from datetime import datetime, timezone

from app.modules import status_from_timeline as sft
from app.services import timeline as timeline_svc

PROJECTION_SOURCE = "timeline:last_effective_hop"


class DirectStatusWriteError(Exception):
    """试图绕过正式时间线直接改写对外状态。"""

    def __init__(self, waybill_id: str, attempted: str | None = None):
        self.waybill_id = waybill_id
        self.attempted = attempted
        super().__init__(
            "拒绝直接改写状态投影：对外状态只能由正式时间线末有效 hop 的 "
            f"event_code 映射得出（运单 {waybill_id}，尝试值 {attempted!r}）。"
            "请改为向正式时间线装载 hop，再由投影服务同事务重算。"
        )


def now_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def refresh(conn, waybill_id: str, *, write_proof: bool = True) -> dict:
    """在同一事务内重算并整体替换投影值，追加状态证明。

    调用方负责事务边界（``BEGIN IMMEDIATE`` / ``commit`` / ``rollback``）。
    运单行必须已存在；``status_proj`` 以「写后读」方式确认落库值。
    """
    derived = sft.derive(conn, waybill_id)
    # 一次性令牌：数据库触发器只接受携带令牌且值等于末 hop 映射的更新，
    # 因此裸 UPDATE 一律失败，而本服务仍走同一条更新语句。
    conn.execute(
        "INSERT INTO projection_write_tokens(waybill_id, proj_value, created_at) VALUES (?,?,?)",
        (waybill_id, derived["status"], now_utc()),
    )
    cur = conn.execute(
        "UPDATE waybills SET status_proj=? WHERE id=?",
        (derived["status"], waybill_id),
    )
    if cur.rowcount != 1:
        raise LookupError(f"运单不存在，无法投影: {waybill_id}")

    persisted = sft.declared_status(conn, waybill_id)
    if persisted != derived["status"]:
        # 理论上不可达；宁可整笔失败也不留下「投影已变但读不回」的状态。
        raise RuntimeError(
            f"投影写后读不一致: {waybill_id} 期望 {derived['status']!r} 实际 {persisted!r}"
        )

    proof = {
        "waybill_id": waybill_id,
        "last_hop_id": derived["last_hop"]["id"] if derived["last_hop"] else None,
        "mapped_code": derived["mapped_code"],
        "proj_value": derived["status"],
        "timeline_digest": derived["timeline_digest"],
        "created_at": now_utc(),
    }
    if write_proof:
        sft.insert_proof(conn, proof)
    return proof


def apply_timeline_change(conn, waybill_id: str) -> dict | None:
    """正式线变更后的统一入口：重算投影 + 追加证明（调用方持有事务）。"""
    return refresh(conn, waybill_id)


def load_hop(conn, hop: dict) -> dict:
    """向正式时间线装载一条 hop，并同事务重算投影。

    返回 ``{"written": bool, "proof": proof|None, "status": str}``。
    重复 hop 不改变正式线，也不会刷新证明（证明只在真实变更时追加）。
    """
    written = timeline_svc.append_primary(conn, hop)
    waybill_id = hop["waybill_id"]
    proof = apply_timeline_change(conn, waybill_id) if written else None
    return {
        "written": written,
        "proof": proof,
        "status": sft.declared_status(conn, waybill_id),
    }


def set_direct(conn, waybill_id: str, value: str) -> None:
    """显式拒绝：对外状态不得由接口/页面直接改写。

    任何调用都会抛错；调用方的事务应以回滚收尾。
    """
    raise DirectStatusWriteError(waybill_id, value)
