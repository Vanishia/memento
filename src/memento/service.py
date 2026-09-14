"""业务层：时间戳生成、注入文本格式化。MCP 与 Web 两个入口都只调这里。"""

from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from . import repository

TZ = ZoneInfo("Asia/Shanghai")

PULL_LIMIT = 5

# 一次能往后追加多少条（翻页）。注入量等于每轮成本，翻得更深就该换检索手段
PULL_EXTEND_MAX = 20

PIN_LIMIT = 15

SEARCH_LIMIT = 10


def _now() -> str:
    # 保留微秒，保证同秒内多次写/改仍有严格的排序先后
    return datetime.now(TZ).strftime("%Y-%m-%d %H:%M:%S.%f")


def write_memory(content: str) -> str:
    return repository.create(content, _now())


def edit_memory(memory_id: str, content: str) -> bool:
    return repository.update(memory_id, content, _now())


def delete_memory(memory_id: str) -> bool:
    return repository.delete(memory_id)


def memory_exists(memory_id: str) -> bool:
    return repository.get(memory_id) is not None


def pin_memory(memory_id: str) -> str:
    row = repository.get(memory_id)
    if row is None:
        return f"错误：不存在 id={memory_id} 的记忆"
    if row["pinned"]:
        return f"已置顶（id={memory_id}）"
    if repository.count_pinned() >= PIN_LIMIT:
        return "已经达到置顶上限，可 unpin 部分记忆、或将部分记忆合并为一条"
    repository.set_pinned(memory_id, True)
    return f"已置顶（id={memory_id}）"


def unpin_memory(memory_id: str) -> str:
    row = repository.get(memory_id)
    if row is None:
        return f"错误：不存在 id={memory_id} 的记忆"
    if not row["pinned"]:
        return f"该记忆未置顶（id={memory_id}）"
    repository.set_pinned(memory_id, False)
    return f"已解除置顶（id={memory_id}）"


def _format_line(r) -> str:
    return f"[{r['id']} {r['updated_at'][:10]}] {r['content']}"


def _library_header(pinned: int, recent: int) -> str:
    """pull 首行的元信息：库的起点、总量、本次注入多少、有多少被挡在外面。

    「库起点」用 created_at 的最小值——列表里显示的日期是 updated_at，随时会被编辑
    刷新，所以起点不能从任何一条的显示日期反推，只能这样单独查出来。
    """
    total = repository.count_total()
    since = repository.earliest_created()
    shown = pinned + recent
    line = f"库 {since[:10] if since else '空'} 起 · 共 {total} 条 · 本次注入 {shown} 条"
    if total > shown:
        line += f"（{total - shown} 条未显示，可 search）"
    return f"── {line} ──"


def pull_memories(extend: int = 0) -> str:
    """注入给 LLM 的文本：元信息 → 置顶 → 短期，每行 `[id 日期] 内容`，id 供 edit 精确指定条目。

    extend：在默认 5 条之外追加的条数，用来一次往后翻页（0-20）。置顶恒定全给。
    非法值回落到 0——调用方是模型，不能指望它每次都传对。
    """
    try:
        extend = int(extend)
    except (TypeError, ValueError):
        extend = 0
    extend = max(0, min(extend, PULL_EXTEND_MAX))

    limit = PULL_LIMIT + extend
    pinned_rows = repository.list_pinned()
    recent_rows = repository.list_latest(limit)
    if not pinned_rows and not recent_rows:
        return "(还没有任何记忆)"
    sections = [_library_header(len(pinned_rows), len(recent_rows))]
    if pinned_rows:
        sections.append("置顶：\n" + "\n".join(_format_line(r) for r in pinned_rows))
    if recent_rows:
        sections.append("短期：\n" + "\n".join(_format_line(r) for r in recent_rows))
    return "\n\n".join(sections)


def search_memories(keyword: str, since: str = "", until: str = "") -> str:
    """搜索记忆，结果按相关性排序，每行 `[id 日期] 内容`。"""
    keyword = keyword.strip()
    if not keyword:
        return "错误：请提供关键词"
    for label, date in (("since", since), ("until", until)):
        if date:
            try:
                datetime.strptime(date, "%Y-%m-%d")
            except ValueError:
                return f"错误：{label} 日期格式应为 YYYY-MM-DD"
    rows = repository.search(keyword, since, until, SEARCH_LIMIT)
    if not rows:
        return f"没有匹配「{keyword}」的记忆"
    return "\n".join(_format_line(r) for r in rows)


def list_memories() -> list[dict]:
    return [
        {
            "id": r["id"],
            "content": r["content"],
            "created_at": r["created_at"],
            "updated_at": r["updated_at"],
            # Web UI 乐观更新需要按 pinned 分区精确保留插入位置
            "pinned": r["pinned"],
        }
        for r in repository.list_all()
    ]
