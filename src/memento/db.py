"""SQLite 连接与建表。schema 变更在此追加 migration。"""

from __future__ import annotations

import random
import sqlite3
import string

from . import config

# 随机字母数字 id：无顺序语义，避免模型把数字大小当作记忆的新旧/重要程度
# 去掉易混字符 0/o 与 1/l，被复述、被拼写时不会认错
_ID_ALPHABET = string.digits[2:] + "".join(c for c in string.ascii_lowercase if c not in "ol")

# id 长度。容量 = len(字母表) ** ID_LENGTH（默认 32 ** 3 = 32768）。
# 加长、或更换字母表都不需要迁移：id 都是随机串，互不冲突，可共存于同一主键列。
ID_LENGTH = 3


def random_id() -> str:
    return "".join(random.choices(_ID_ALPHABET, k=ID_LENGTH))


def id_capacity() -> int:
    return len(_ID_ALPHABET) ** ID_LENGTH


SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id         TEXT PRIMARY KEY,
    content    TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL,
    pinned     INTEGER NOT NULL DEFAULT 0
);
-- 时间戳格式：'YYYY-MM-DD HH:MM:SS.ffffff'（东八区，微秒用于同秒内排序）
CREATE INDEX IF NOT EXISTS idx_memories_updated ON memories(updated_at DESC, id DESC);
"""


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(config.db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        cols = {row[1]: row[2] for row in conn.execute("PRAGMA table_info(memories)")}
        # 旧库 id 为 INTEGER 自增：重建表，回填随机字母 id（含 pinned 列）
        if cols.get("id", "").upper() == "INTEGER":
            _migrate_text_id(conn)
        # TEXT id 但缺 pinned 列的旧库：直接补列
        elif "pinned" not in cols:
            conn.execute(
                "ALTER TABLE memories ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0"
            )


def _migrate_text_id(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        "SELECT content, created_at, updated_at FROM memories ORDER BY id"
    ).fetchall()
    conn.execute("ALTER TABLE memories RENAME TO memories_old")
    conn.execute(
        """
        CREATE TABLE memories (
            id         TEXT PRIMARY KEY,
            content    TEXT    NOT NULL,
            created_at TEXT    NOT NULL,
            updated_at TEXT    NOT NULL,
            pinned     INTEGER NOT NULL DEFAULT 0
        )
        """
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_memories_updated"
        " ON memories(updated_at DESC, id DESC)"
    )
    used: set[str] = set()
    for row in rows:
        memory_id = random_id()
        while memory_id in used:
            memory_id = random_id()
        used.add(memory_id)
        conn.execute(
            "INSERT INTO memories (id, content, created_at, updated_at, pinned)"
            " VALUES (?, ?, ?, ?, 0)",
            (memory_id, row["content"], row["created_at"], row["updated_at"]),
        )
    conn.execute("DROP TABLE memories_old")
