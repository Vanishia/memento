"""数据访问层：纯 CRUD，不含业务逻辑。"""

from __future__ import annotations

import sqlite3

from .db import get_conn, random_id

_ORDER = "updated_at DESC, id DESC"


def create(content: str, ts: str) -> str:
    # 主键冲突即 id 撞车，换一个新的重试
    for _ in range(100):
        memory_id = random_id()
        try:
            with get_conn() as conn:
                conn.execute(
                    "INSERT INTO memories (id, content, created_at, updated_at)"
                    " VALUES (?, ?, ?, ?)",
                    (memory_id, content, ts, ts),
                )
            return memory_id
        except sqlite3.IntegrityError:
            continue
    raise RuntimeError("无法生成唯一 id（记忆条数可能已接近 26*26 上限）")


def update(memory_id: str, content: str, ts: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE memories SET content = ?, updated_at = ? WHERE id = ?",
            (content, ts, memory_id),
        )
        return cur.rowcount > 0


def delete(memory_id: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
        return cur.rowcount > 0


def get(memory_id: str) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()


def set_pinned(memory_id: str, pinned: bool) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE memories SET pinned = ? WHERE id = ?",
            (int(pinned), memory_id),
        )
        return cur.rowcount > 0


def count_pinned() -> int:
    with get_conn() as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM memories WHERE pinned = 1"
        ).fetchone()[0]


def list_pinned() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM memories WHERE pinned = 1 ORDER BY {_ORDER}"
        ).fetchall()


def list_latest(limit: int) -> list[sqlite3.Row]:
    """最近的短期（未置顶）记忆。"""
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM memories WHERE pinned = 0 ORDER BY {_ORDER} LIMIT ?",
            (limit,),
        ).fetchall()


def list_all() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM memories ORDER BY pinned DESC, {_ORDER}"
        ).fetchall()


def search(
    keyword: str, since: str = "", until: str = "", limit: int = 10
) -> list[sqlite3.Row]:
    """关键词子串搜索。相关性 = 关键词首次出现位置靠前，同位置按更新时间倒序。"""
    sql = "SELECT * FROM memories WHERE content LIKE '%' || ? || '%'"
    args: list = [keyword]
    if since:
        sql += " AND substr(updated_at, 1, 10) >= ?"
        args.append(since)
    if until:
        sql += " AND substr(updated_at, 1, 10) <= ?"
        args.append(until)
    sql += " ORDER BY INSTR(content, ?) ASC, updated_at DESC LIMIT ?"
    args += [keyword, limit]
    with get_conn() as conn:
        return conn.execute(sql, args).fetchall()
