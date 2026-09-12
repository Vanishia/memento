"""配置读取：全部来自环境变量 / .env 文件。"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()


def db_path() -> Path:
    return Path(os.environ.get("MEMENTO_DB_PATH", "./memento.db")).expanduser()


def host() -> str:
    return os.environ.get("MEMENTO_HOST", "127.0.0.1")


def port() -> int:
    return int(os.environ.get("MEMENTO_PORT", "8765"))


def password() -> str:
    """Web UI 登录密码；空字符串表示免登录。"""
    return os.environ.get("MEMENTO_PASSWORD", "")


def mcp_host() -> str:
    return os.environ.get("MEMENTO_MCP_HOST", "127.0.0.1")


def mcp_port() -> int:
    return int(os.environ.get("MEMENTO_MCP_PORT", "8766"))


def backup_dir() -> Path:
    """备份根目录：snapshots/（自动轮换）、archive/（长期保留）、restore-safety/。"""
    default = str(db_path().parent / "backups")
    return Path(os.environ.get("MEMENTO_BACKUP_DIR", default)).expanduser()


def snapshot_keep_days() -> int:
    """快照保留天数，早于该天数的旧快照在 snapshot 时自动删除。0 = 不自动清理。"""
    return int(os.environ.get("MEMENTO_SNAPSHOT_KEEP_DAYS", "10"))
