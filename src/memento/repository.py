"""数据访问层：纯 CRUD，不含业务逻辑。"""

from __future__ import annotations

import sqlite3

from .db import get_conn

_ORDER = "updated_at DESC, id DESC"


def create(content: str, ts: str) -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "INSERT INTO memories (content, created_at, updated_at) VALUES (?, ?, ?)",
            (content, ts, ts),
        )
        return cur.lastrowid


def update(memory_id: int, content: str, ts: str) -> bool:
    with get_conn() as conn:
        cur = conn.execute(
            "UPDATE memories SET content = ?, updated_at = ? WHERE id = ?",
            (content, ts, memory_id),
        )
        return cur.rowcount > 0


def get(memory_id: int) -> sqlite3.Row | None:
    with get_conn() as conn:
        return conn.execute("SELECT * FROM memories WHERE id = ?", (memory_id,)).fetchone()


def list_latest(limit: int) -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(
            f"SELECT * FROM memories ORDER BY {_ORDER} LIMIT ?", (limit,)
        ).fetchall()


def list_all() -> list[sqlite3.Row]:
    with get_conn() as conn:
        return conn.execute(f"SELECT * FROM memories ORDER BY {_ORDER}").fetchall()
