"""Web UI（FastAPI）。用法：python -m memento.web.app

鉴权：.env 里配置 MEMENTO_PASSWORD 后，POST /api/login 校验密码，
成功后下发 HttpOnly Cookie；其余 /api/* 都要求该 Cookie。
不配密码则全部放行（本地模式）。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
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


class PinIn(BaseModel):
    pinned: bool


def _session_max_age() -> int:
    return config.session_max_days() * 24 * 3600


def _session_idle_age() -> int:
    return config.session_idle_days() * 24 * 3600


def _password_fingerprint() -> str:
    return hashlib.sha256(config.password().encode()).hexdigest()


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _session_token(request: Request) -> str:
    return request.cookies.get(COOKIE_NAME, "")


def _valid_session(request: Request, *, touch: bool) -> bool:
    if not config.password():
        return True
    token = _session_token(request)
    if not token:
        return False
    now = int(time.time())
    token_hash = _token_hash(token)
    with _session_db() as conn:
        row = conn.execute(
            "SELECT last_seen_at, expires_at, password_fingerprint, revoked_at "
            "FROM web_sessions WHERE token_hash = ?",
            (token_hash,),
        ).fetchone()
        if row is None or row["revoked_at"] is not None:
            return False
        if row["password_fingerprint"] != _password_fingerprint():
            return False
        if row["expires_at"] <= now or row["last_seen_at"] + _session_idle_age() <= now:
            conn.execute(
                "UPDATE web_sessions SET revoked_at = ? WHERE token_hash = ?",
                (now, token_hash),
            )
            return False
        if touch:
            conn.execute(
                "UPDATE web_sessions SET last_seen_at = ? WHERE token_hash = ?",
                (now, token_hash),
            )
        return True


def _session_db():
    # Keep the auth table in the same SQLite database as memories so existing
    # backup/restore operations include it automatically.
    from ..db import get_conn

    return get_conn()


def _authed(request: Request) -> bool:
    return _valid_session(request, touch=False)


def require_auth(request: Request) -> None:
    if not _valid_session(request, touch=True):
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
    # This endpoint is deliberately read-only so a frontend status watcher
    # cannot keep an idle session alive by polling it.
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
    now = int(time.time())
    raw_token = secrets.token_urlsafe(32)
    with _session_db() as conn:
        # Old session rows are harmless after their password fingerprint no
        # longer matches; prune expired/revoked rows while a user logs in.
        conn.execute(
            "DELETE FROM web_sessions WHERE revoked_at IS NOT NULL OR expires_at <= ?",
            (now,),
        )
        conn.execute(
            "INSERT INTO web_sessions "
            "(token_hash, created_at, last_seen_at, expires_at, password_fingerprint) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                _token_hash(raw_token),
                now,
                now,
                now + _session_max_age(),
                _password_fingerprint(),
            ),
        )
    response.set_cookie(
        COOKIE_NAME,
        raw_token,
        max_age=_session_max_age(),
        httponly=True,
        samesite="lax",
    )
    return {"ok": True}


@app.post("/api/logout")
def logout(request: Request, response: Response) -> dict:
    token = _session_token(request)
    if token:
        with _session_db() as conn:
            conn.execute(
                "UPDATE web_sessions SET revoked_at = ? WHERE token_hash = ?",
                (int(time.time()), _token_hash(token)),
            )
    response.delete_cookie(COOKIE_NAME)
    return {"ok": True}


@app.get("/api/memories")
def list_memories(_: None = Depends(require_auth)) -> list[dict]:
    return service.list_memories()


@app.post("/api/memories", status_code=201)
def create_memory(body: MemoryIn, _: None = Depends(require_auth)) -> dict:
    memory_id = service.write_memory(body.content)
    return {"id": memory_id}


@app.get("/api/memories/search")
def search_memories(
    keyword: str = "", since: str = "", until: str = "",
    _: None = Depends(require_auth),
) -> dict:
    try:
        items = service.find_memories(keyword, since, until)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None
    return {
        "items": items,
        "limit": service.SEARCH_LIMIT,
        "may_have_more": len(items) >= service.SEARCH_LIMIT,
    }


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


@app.put("/api/memories/{memory_id}/pin")
def pin_memory(
    memory_id: str, body: PinIn, _: None = Depends(require_auth)
) -> dict:
    if not service.memory_exists(memory_id):
        raise HTTPException(status_code=404, detail="记忆不存在")
    message = (
        service.pin_memory(memory_id) if body.pinned
        else service.unpin_memory(memory_id)
    )
    if message.startswith("已经达到"):
        raise HTTPException(status_code=400, detail=message)
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
