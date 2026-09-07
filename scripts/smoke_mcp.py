"""MCP server 冒烟测试：通过 stdio 真实拉起 server 并调用三个工具。

用法：.venv/Scripts/python scripts/smoke_mcp.py
"""

import asyncio
import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

os.environ["MEMENTO_DB_PATH"] = "./smoke_mcp.db"

# 用当前虚拟环境的 python 拉起 server 子进程
server = StdioServerParameters(
    command=sys.executable,
    args=["-m", "memento.mcp_server"],
    env={**os.environ},
)


async def main() -> None:
    async with stdio_client(server) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()

            tools = await session.list_tools()
            names = [t.name for t in tools.tools]
            print("tools:", names)
            assert names == ["pull", "write", "edit"]

            r = await session.call_tool("write", {"content": "mcp 冒烟第一条"})
            print("write ->", r.content[0].text)
            r = await session.call_tool("write", {"content": "mcp 冒烟第二条"})
            print("write ->", r.content[0].text)

            r = await session.call_tool("edit", {"id": 1, "content": "mcp 冒烟第一条（已改）"})
            print("edit  ->", r.content[0].text)
            r = await session.call_tool("edit", {"id": 999, "content": "x"})
            assert "不存在" in r.content[0].text
            print("edit 不存在 id ->", r.content[0].text)

            r = await session.call_tool("pull", {})
            text = r.content[0].text
            print("pull ->")
            print(text)
            assert "已改" in text.splitlines()[0], "edit 后应置顶"
            assert "999" not in text
            print("MCP 冒烟全部通过")


asyncio.run(main())
