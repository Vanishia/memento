"""Web UI（FastAPI）。用法：python -m memento.web.app

鉴权：.env 里配置 MEMENTO_PASSWORD 后，POST /api/login 校验密码，
成功后下发 HttpOnly Cookie；其余 /api/* 都要求该 Cookie。
不配密码则全部放行（本地模式）。
"""

from __future__ import annotations

import hashlib
import hmac
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from .. import config, service
from ..db import init_db

STATIC_DIR = Path(__file__).parent / "static"
COOKIE_NAME = "memento_session"
COOKIE_MAX_AGE = 30 * 24 * 3600  # 30 天

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


@app.get("/api/auth_status")
def auth_status(request: Request) -> dict:
    return {"auth_required": bool(config.password()), "authed": _authed(request)}


@app.post("/api/login")
def login(body: LoginIn, response: Response) -> dict:
    if not config.password():
        return {"ok": True}
    if not hmac.compare_digest(body.password, config.password()):
        raise HTTPException(status_code=401, detail="密码错误")
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
    memory_id: int, body: MemoryIn, _: None = Depends(require_auth)
) -> dict:
    if not service.edit_memory(memory_id, body.content):
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"ok": True}


@app.delete("/api/memories/{memory_id}")
def delete_memory(memory_id: int, _: None = Depends(require_auth)) -> dict:
    if not service.delete_memory(memory_id):
        raise HTTPException(status_code=404, detail="记忆不存在")
    return {"ok": True}


@app.get("/")
def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


def main() -> None:
    init_db()
    import uvicorn

    uvicorn.run(app, host=config.host(), port=config.port())


if __name__ == "__main__":
    main()
