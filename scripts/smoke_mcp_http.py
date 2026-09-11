"""MCP HTTP（streamable-http）模式冒烟测试：真实拉起 HTTP server 并调用工具。

用法：.venv/Scripts/python scripts/smoke_mcp_http.py
"""

import asyncio
import os
import subprocess
import sys
import time
import urllib.request

os.environ["MEMENTO_DB_PATH"] = "./smoke_mcp_http.db"
os.environ["MEMENTO_MCP_PORT"] = "8767"

from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

URL = "http://127.0.0.1:8767/mcp/"


def wait_ready(timeout: float = 15.0) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            urllib.request.urlopen(URL, timeout=1)
        except Exception:
            # 端口能连通就算就绪（业务错误无妨）
            return
        time.sleep(0.3)
    raise RuntimeError("server 未就绪")


async def main() -> None:
    proc = subprocess.Popen(
        [sys.executable, "-c", "from memento.mcp_server import main_http; main_http()"],
        env=dict(os.environ),
    )
    try:
        wait_ready()
        async with streamablehttp_client(URL) as (read, write, _):
            async with ClientSession(read, write) as session:
                await session.initialize()
                tools = await session.list_tools()
                assert [t.name for t in tools.tools] == ["pull", "write", "edit", "pin"]
                r = await session.call_tool("write", {"content": "http 模式冒烟"})
                print("write ->", r.content[0].text)
                r = await session.call_tool("pull", {})
                print("pull ->")
                print(r.content[0].text)
                assert "http 模式冒烟" in r.content[0].text
        print("MCP HTTP 冒烟全部通过")
    finally:
        proc.terminate()
        proc.wait(timeout=10)


asyncio.run(main())
