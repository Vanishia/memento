"""MCP server 冒烟测试：通过 stdio 真实拉起 server 并调用三个工具。

用法：.venv/Scripts/python scripts/smoke_mcp.py
"""

import asyncio
import os
import sys
from datetime import datetime
from zoneinfo import ZoneInfo

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
            assert names == ["pull", "write", "edit", "pin", "search"]

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
            assert text.splitlines()[0].startswith("── 库"), "pull 首行应为库元信息"
            first_line = next(l for l in text.splitlines() if l.startswith("["))
            assert "已改" in first_line, "edit 后应排在短期区最前（最近更新优先）"
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

            # 短期条数：默认 5 条，extend 在默认之外追加（往后翻页）
            for i in range(20):
                await session.call_tool("write", {"content": f"翻页测试第{i}条"})
            r = await session.call_tool("pull", {})
            text = r.content[0].text
            assert len(text.split("短期：")[1].strip().splitlines()) == 5, "默认应注入 5 条"
            print("pull 默认 -> 5 条 |", text.splitlines()[0])

            r = await session.call_tool("pull", {"extend": 20})
            n = len(r.content[0].text.split("短期：")[1].strip().splitlines())
            assert n == 22, f"extend=20 应取 5+20=25 条（库内仅 22 条），实际 {n}"
            print("pull extend=20 ->", n, "条")

            r = await session.call_tool("pull", {"extend": -5})  # 非法值回落到 0
            assert len(r.content[0].text.split("短期：")[1].strip().splitlines()) == 5
            print("pull extend=-5 回落 -> 5 条")

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

            r = await session.call_tool("search", {"keyword": "上限测试"})
            text = r.content[0].text
            assert "上限测试第15条" in text and "上限测试第0条" not in text
            print("search ->")
            print(text)
            r = await session.call_tool("search", {"keyword": "不存在的关键词xyz"})
            assert "没有匹配" in r.content[0].text
            print("search 无结果 ->", r.content[0].text)
            r = await session.call_tool("search", {"keyword": "上限测试", "since": "2099-01-01"})
            assert "没有匹配" in r.content[0].text
            print("search since 未来 ->", r.content[0].text)
            # 空关键词：须带日期范围；带范围时退化为"取那几天的全部记忆"
            r = await session.call_tool("search", {"keyword": ""})
            assert "须限定" in r.content[0].text
            print("search 空关键词无范围 ->", r.content[0].text)
            today = datetime.now(ZoneInfo("Asia/Shanghai")).strftime("%Y-%m-%d")
            r = await session.call_tool(
                "search", {"keyword": "   ", "since": today, "until": today}
            )
            text = r.content[0].text
            assert "上限测试" in text and "没有匹配" not in text
            print("search 空关键词+今天 ->", len(text.splitlines()), "行")
            assert "仅列出" in text, "满额时应提示可能被截断"
            r = await session.call_tool(
                "search", {"keyword": "", "since": today, "until": "2020-01-01"}
            )
            assert "没有匹配" in r.content[0].text and "须限定" not in r.content[0].text
            print("search 空关键词+空范围 ->", r.content[0].text)

            r = await session.call_tool("search", {"keyword": "上限测试", "since": "bad-date"})
            assert "YYYY-MM-DD" in r.content[0].text
            print("search 日期非法 ->", r.content[0].text)
            print("MCP 冒烟全部通过")


asyncio.run(main())
