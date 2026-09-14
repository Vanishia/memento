"""MCP server 入口。

- 本机使用（stdio）：memento-mcp  或  python -m memento.mcp_server
- 远程部署（HTTP）： memento-mcp-http，由 nginx 反代并校验 Bearer token
"""

from __future__ import annotations

from mcp.server.fastmcp import FastMCP

from . import config, service
from .db import init_db

mcp = FastMCP("memento", host=config.mcp_host(), port=config.mcp_port())


@mcp.tool()
def pull(extend: int = 0) -> str:
    """拉取最近的记忆条目，格式 `[id 日期] 内容`。首行是库的元信息（起始日期、总条数、本次注入条数）。默认取最近 5 条；需要往回翻时传 extend（0-20），在 5 条之外追加同样多条，像翻页。置顶条目恒定全部返回。每次对话开始时调用以恢复上下文。"""
    return service.pull_memories(extend)


@mcp.tool()
def write(content: str) -> str:
    """创建一条新记忆。content 为要记住的内容，支持换行、markdown。自动附加当日时间戳。"""
    memory_id = service.write_memory(content)
    return f"已记住（id={memory_id}）"


@mcp.tool()
def edit(id: str, content: str) -> str:
    """编辑某条记忆。id 为 pull 返回行首的字母数字编号，content 为替换后的完整内容。"""
    if service.edit_memory(id, content):
        return f"已更新（id={id}）"
    return f"错误：不存在 id={id} 的记忆"


@mcp.tool()
def pin(id: str, unpin: bool = False) -> str:
    """置顶重要的、长期有效的记忆。id 为 pull 返回的字母编号，unpin=true 时解除置顶。"""
    if unpin:
        return service.unpin_memory(id)
    return service.pin_memory(id)


@mcp.tool()
def search(keyword: str, since: str = "", until: str = "") -> str:
    """查找更久远的记忆。单关键词搜索，此工具只搜索记忆库内记忆。since/until 限定更新日期范围（YYYY-MM-DD），留空不限。"""
    return service.search_memories(keyword, since, until)


def main() -> None:
    """stdio 模式：由本机 MCP 客户端直接拉起。"""
    init_db()
    mcp.run()


def main_http() -> None:
    """HTTP（streamable-http）模式：用于 VPS 部署，鉴权交给 nginx。"""
    init_db()
    mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
