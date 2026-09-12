"""备份与恢复：快照（自动轮换）、长期归档、恢复。

不走 MCP / Web UI：在 VPS 上由 systemd timer 定时拉起，也可手动运行
`memento-backup snapshot|archive|restore`。
"""

from __future__ import annotations

import argparse
import sqlite3
import sys
import time
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from . import config
from .db import get_conn

# 文件名时间戳与记忆时间戳保持一致，都用东八区
_TZ = ZoneInfo("Asia/Shanghai")

_REQUIRED_COLS = {"id", "content", "created_at", "updated_at", "pinned"}

_SELECT_COLS = "id, content, created_at, updated_at, pinned"


def _ts() -> str:
    return datetime.now(_TZ).strftime("%Y%m%d-%H%M%S")


def _filename() -> str:
    return f"memento-{_ts()}.db"


def _online_backup(src: Path, dst: Path) -> None:
    """SQLite 在线备份 API：一致性地拷贝整个库（WAL 模式下也安全）。"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    src_conn = sqlite3.connect(str(src))
    try:
        dst_conn = sqlite3.connect(str(dst))
        try:
            src_conn.backup(dst_conn)
        finally:
            dst_conn.close()
    finally:
        src_conn.close()


def _prune(directory: Path, keep_days: int) -> int:
    """删除 directory 下修改时间早于 keep_days 天的 .db 文件，返回删除数量。"""
    if keep_days <= 0 or not directory.is_dir():
        return 0
    cutoff = time.time() - keep_days * 86400
    n = 0
    for f in directory.glob("*.db"):
        if f.stat().st_mtime < cutoff:
            f.unlink()
            n += 1
    return n


def snapshot() -> Path:
    """快照：备份当前库到 snapshots/，并清理超过保留期的旧快照。"""
    dst = config.backup_dir() / "snapshots" / _filename()
    _online_backup(config.db_path(), dst)
    pruned = _prune(config.backup_dir() / "snapshots", config.snapshot_keep_days())
    print(f"快照已保存：{dst}")
    if pruned:
        print(f"已清理 {pruned} 个超过 {config.snapshot_keep_days()} 天的旧快照")
    return dst


def archive() -> Path:
    """长期归档：备份当前库到 archive/，不自动删除。"""
    dst = config.backup_dir() / "archive" / _filename()
    _online_backup(config.db_path(), dst)
    print(f"长期备份已保存：{dst}")
    return dst


def _validate_snapshot(path: Path) -> None:
    if not path.is_file():
        raise SystemExit(f"错误：快照文件不存在：{path}")
    try:
        conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    except sqlite3.Error as e:
        raise SystemExit(f"错误：无法打开快照文件：{e}")
    try:
        row = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='memories'"
        ).fetchone()
        if row is None:
            raise SystemExit(f"错误：{path} 里没有 memories 表，不是 Memento 数据库")
        cols = {r[1] for r in conn.execute("PRAGMA table_info(memories)")}
        if not _REQUIRED_COLS <= cols:
            raise SystemExit("错误：快照的 memories 表缺少必要字段，无法恢复")
    finally:
        conn.close()


def restore(snapshot_path: Path, merge: bool) -> Path:
    """把快照导入现有数据库，返回恢复前自动备份的路径。

    默认整体替换：先清空 memories，再写入快照内容；
    merge=True 时只导入当前库里不存在的条目（INSERT OR IGNORE），现有条目不动。
    两种方式都会先把当前库备份到 restore-safety/。
    """
    _validate_snapshot(snapshot_path)
    safety = config.backup_dir() / "restore-safety" / f"memento-before-restore-{_ts()}.db"
    _online_backup(config.db_path(), safety)

    conn = get_conn()
    try:
        # ATTACH 不能在事务内执行，所以先 ATTACH、随后 DML 才进事务
        conn.execute("ATTACH DATABASE ? AS snap", (str(snapshot_path),))
        try:
            with conn:
                if merge:
                    conn.execute(
                        f"INSERT OR IGNORE INTO memories ({_SELECT_COLS})"
                        f" SELECT {_SELECT_COLS} FROM snap.memories"
                    )
                    print(f"已合并 {conn.total_changes} 条缺失的记忆（现有数据未改动）")
                else:
                    conn.execute("DELETE FROM memories")
                    conn.execute(
                        f"INSERT INTO memories ({_SELECT_COLS})"
                        f" SELECT {_SELECT_COLS} FROM snap.memories"
                    )
                    print("已用快照整体替换当前记忆库")
        finally:
            conn.execute("DETACH DATABASE snap")
    finally:
        conn.close()
    print(f"恢复前的数据库已备份到：{safety}")
    return safety


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="memento-backup",
        description="Memento 记忆库备份：快照（自动轮换）、长期归档、恢复。",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("snapshot", help="备份快照到 snapshots/，清理超过保留期的旧快照")
    sub.add_parser("archive", help="备份长期归档到 archive/，不自动删除")

    p_restore = sub.add_parser("restore", help="把快照导入现有数据库")
    p_restore.add_argument("file", type=Path, help="快照文件路径")
    p_restore.add_argument(
        "--merge",
        action="store_true",
        help="只导入当前库里不存在的条目，不覆盖/清空现有数据",
    )

    args = parser.parse_args(argv)
    if not config.db_path().is_file():
        parser.exit(1, f"错误：数据库文件不存在：{config.db_path()}\n")

    if args.command == "snapshot":
        snapshot()
    elif args.command == "archive":
        archive()
    elif args.command == "restore":
        restore(args.file, args.merge)


if __name__ == "__main__":
    sys.exit(main())
