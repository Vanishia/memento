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
            assert names == ["pull", "write", "edit", "pin"]

            r = await session.call_tool("write", {"content": "mcp 冒烟第一条"})
            print("write ->", r.content[0].text)
            first_id = r.content[0].text.split("id=")[1].rstrip("）")
            r = await session.call_tool("write", {"content": "mcp 冒烟第二条"})
            print("write ->", r.content[0].text)

            r = await session.call_tool(
                "edit", {"id": first_id, "content": "mcp 冒烟第一条（已改）"}
            )
            print("edit  ->", r.content[0].text)
            r = await session.call_tool("edit", {"id": "@@", "content": "x"})
            assert "不存在" in r.content[0].text
            print("edit 不存在 id ->", r.content[0].text)

            r = await session.call_tool("pull", {})
            text = r.content[0].text
            print("pull ->")
            print(text)
            assert "已改" in text.splitlines()[1], "edit 后短期区应置顶"
            assert first_id in text, "pull 应包含 id"
            assert "@@" not in text

            r = await session.call_tool("pin", {"id": first_id})
            assert "已置顶" in r.content[0].text
            print("pin   ->", r.content[0].text)
            r = await session.call_tool("pin", {"id": first_id})  # 重复置顶应幂等
            assert "已置顶" in r.content[0].text
            r = await session.call_tool("pin", {"id": "@@"})
            assert "不存在" in r.content[0].text
            print("pin 不存在 id ->", r.content[0].text)

            r = await session.call_tool("pull", {})
            text = r.content[0].text
            assert "置顶：" in text and first_id in text.split("短期：")[0]
            print("pull 分节 ->")
            print(text)

            r = await session.call_tool("pin", {"id": first_id, "unpin": True})
            assert "已解除置顶" in r.content[0].text
            print("unpin ->", r.content[0].text)
            r = await session.call_tool("pin", {"id": first_id, "unpin": True})
            assert "未置顶" in r.content[0].text

            # 置顶上限：第 16 条应返回上限提示
            results = []
            for i in range(16):
                r = await session.call_tool("write", {"content": f"上限测试第{i}条"})
                wid = r.content[0].text.split("id=")[1].rstrip("）")
                r = await session.call_tool("pin", {"id": wid})
                results.append(r.content[0].text)
            assert all("已置顶" in m for m in results[:15])
            assert "上限" in results[15]
            print("第 16 次 pin ->", results[15])
            print("MCP 冒烟全部通过")


asyncio.run(main())
