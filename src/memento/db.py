"""SQLite 连接与建表。schema 变更在此追加 migration。"""

from __future__ import annotations

import sqlite3

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    content    TEXT    NOT NULL,
    created_at TEXT    NOT NULL,
    updated_at TEXT    NOT NULL
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
