"""FastAPI desk. JSON once a second. Read-only."""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel

from desk.runtime import Desk

STATIC = Path(__file__).resolve().parent / "static"
desk = Desk()


@asynccontextmanager
async def lifespan(_app: FastAPI):
    await desk.start()
    yield
    await desk.stop()


app = FastAPI(title="Kalshi 15m trade desk", lifespan=lifespan)


class SettingBody(BaseModel):
    strategy: str | None = None
    key: str | None = None
    value: float | None = None
    active: str | None = None


@app.get("/")
async def index():
    return FileResponse(STATIC / "index.html")


@app.get("/api/health")
async def health():
    return {"ok": True, "authed": desk.authed, "observe_only": True}


@app.get("/api/state")
async def state():
    async with desk._lock:
        return desk.snapshot()


@app.websocket("/ws")
async def stream(socket: WebSocket):
    await socket.accept()
    queue: asyncio.Queue = asyncio.Queue(maxsize=1)
    desk.listeners.append(queue)
    try:
        async with desk._lock:
            payload = desk.snapshot()
        await socket.send_json(payload)
        while True:
            await socket.send_json(await queue.get())
    except WebSocketDisconnect:
        pass
    finally:
        if queue in desk.listeners:
            desk.listeners.remove(queue)


@app.post("/api/settings")
async def settings(body: SettingBody):
    async with desk._lock:
        return desk.update_setting(body.active, body.strategy, body.key, body.value)


@app.post("/api/settings/reset")
async def reset_settings():
    async with desk._lock:
        return desk.reset_settings()


@app.post("/api/journal/clear")
async def clear_journal():
    async with desk._lock:
        return desk.clear_journal()
