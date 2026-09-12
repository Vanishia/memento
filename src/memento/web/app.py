"""Web UI（FastAPI）。用法：python -m memento.web.app

鉴权：.env 里配置 MEMENTO_PASSWORD 后，POST /api/login 校验密码，
成功后下发 HttpOnly Cookie；其余 /api/* 都要求该 Cookie。
不配密码则全部放行（本地模式）。
"""

from __future__ import annotations

import hashlib
import hmac
import threading
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import config, service
from ..db import init_db

STATIC_DIR = Path(__file__).parent / "static"
COOKIE_NAME = "memento_session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 天

# 登录限速：按客户端 IP 记录连续失败次数，登录前 sleep 指数退避的惩罚延迟，
# 拖慢在线暴力破解。内存态（单进程够用），重启即清零；nginx limit_req 是第一道防线。
LOGIN_FAIL_WINDOW = 600.0  # 失败记录保留 10 分钟，之后重新计次
LOGIN_BACKOFF_CAP = 15.0  # 单次惩罚延迟上限（秒）
_login_fail: dict[str, tuple[int, float]] = {}  # ip -> (连续失败次数, 最近失败时间)
_login_fail_lock = threading.Lock()

app = FastAPI(title="memento")


class MemoryIn(BaseModel):
    content: str = Field(min_length=1)


class LoginIn(BaseModel):
    password: str


def _expected_token() -> str:
    """由密码派生的会话令牌；改密码即全员下线。"""
    return hmac.new(
        config.password().encode(), b"memento-session", hashlib.sha256
    ).hexdigest()


def _authed(request: Request) -> bool:
    if not config.password():
        return True
    token = request.cookies.get(COOKIE_NAME, "")
    return hmac.compare_digest(token, _expected_token())


def require_auth(request: Request) -> None:
    if not _authed(request):
        raise HTTPException(status_code=401, detail="unauthorized")


def _client_ip(request: Request) -> str:
    # 优先 CF-Connecting-IP：站点在 Cloudflare 后面时它是真实访客 IP。
    # 不能直接用 X-Forwarded-For 首个 IP——CF 只会把访客 IP 追加到该头末尾，
    # 首个 IP 是客户端自己设的，伪造它就能让下面的退避永远从新 IP 重新计。
    # 前提：源站防火墙只放行 CF 网段，防止直连源站者伪造该头。
    cf_ip = request.headers.get("cf-connecting-ip")
    if cf_ip:
        return cf_ip.strip()
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "?"


def _login_backoff(ip: str) -> float:
    """该 IP 当前应承受的登录延迟（秒），随失败次数指数增长。"""
    with _login_fail_lock:
        count, last = _login_fail.get(ip, (0, 0.0))
        if time.monotonic() - last > LOGIN_FAIL_WINDOW:
            count = 0
        return min(2.0**count, LOGIN_BACKOFF_CAP)


def _record_login_fail(ip: str) -> None:
    with _login_fail_lock:
        count, _ = _login_fail.get(ip, (0, 0.0))
        _login_fail[ip] = (count + 1, time.monotonic())


def _clear_login_fail(ip: str) -> None:
    with _login_fail_lock:
        _login_fail.pop(ip, None)


@app.get("/api/auth_status")
def auth_status(request: Request) -> dict:
    return {"auth_required": bool(config.password()), "authed": _authed(request)}


@app.post("/api/login")
def login(body: LoginIn, request: Request, response: Response) -> dict:
    if not config.password():
        return {"ok": True}
    ip = _client_ip(request)
    time.sleep(_login_backoff(ip))  # 失败越多等越久；sleep 在线程池里，不阻塞事件循环
    if not hmac.compare_digest(body.password, config.password()):
        _record_login_fail(ip)
        raise HTTPException(status_code=401, detail="密码错误")
    _clear_login_fail(ip)
    response.set_cookie(
        COOKIE_NAME,
        _expected_token(),
        max_age=COOKIE_MAX_AGE,
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}


@app.post("/api/logout")
def logout(response: Response) -> dict:
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@app.get("/api/memories")
def list_memories(_: None = Depends(require_auth)) -> list[dict]:
    return service.list_memories()


@app.post("/api/memories", status_code=201)
def create_memory(body: MemoryIn, _: None = Depends(require_auth)) -> dict:
    memory_id = service.write_memory(body.content)
    return {"id": memory_id}


@app.put("/api/memories/{memory_id}")
def update_memory(
    memory_id: str, body: MemoryIn, _: None = Depends(require_auth)
) -> dict:
    if not service.edit_memory(memory_id, body.content):
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"ok": True}


@app.delete("/api/memories/{memory_id}")
def delete_memory(memory_id: str, _: None = Depends(require_auth)) -> dict:
    if not service.delete_memory(memory_id):
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/favicon.svg")
def favicon() -> FileResponse:
    return FileResponse(STATIC_DIR / "favicon.svg")


def main() -> None:
    init_db()
    import uvicorn

    uvicorn.run(app, host=config.host(), port=config.port())


if __name__ == "__main__":
    main()
