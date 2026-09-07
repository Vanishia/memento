"""业务层：时间戳生成、注入文本格式化。MCP 与 Web 两个入口都只调这里。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from . import repository

TZ = ZoneInfo("Asia/Shanghai")

PULL_LIMIT = 5


def _now() -> str:
    # 保留微秒，保证同秒内多次写/改仍有严格的排序先后
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S.%f")


def write_memory(content: str) -> int:
    return repository.create(content, _now())


def edit_memory(memory_id: int, content: str) -> bool:
    return repository.update(memory_id, content, _now())


def memory_exists(memory_id: int) -> bool:
    return repository.get(memory_id) is not None


def pull_memories(limit: int = PULL_LIMIT) -> str:
    """注入给 LLM 的文本：只含日期，不含具体时间。"""
    rows = repository.list_latest(limit)
    if not rows:
        return "(还没有任何记忆)"
    return "\n".join(f"[{r['updated_at'][:10]}] {r['content']}" for r in rows)


def list_memories() -> list[dict]:
    return [
        {
            "id": r["id"],
            "content": r["content"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
        }
        for r in repository.list_all()
    ]
