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
    asset: str | None = None
    paper_edge_basis: str | None = None
    paper_min_net_edge_cents: float | None = None
    paper_ignore_edge_gate: bool | None = None
    paper_fade_model: bool | None = None
    paper_fade_trigger_cents: float | None = None
    weekend_timezone: str | None = None
    weekend_feed_freshness_enabled: bool | None = None
    weekend_feed_max_age_secs: float | None = None
    paper_momentum_gate_enabled: bool | None = None
    meas_settlement_window: bool | None = None
    meas_book_metrics: bool | None = None
    meas_window_features: bool | None = None
    meas_liquidation: bool | None = None
    meas_price_buckets: bool | None = None


@app.get("/")
async def index():
    return FileResponse(
        STATIC / "index.html",
        headers={"Cache-Control": "no-store, no-cache, must-revalidate", "Pragma": "no-cache"},
    )


@app.get("/api/health")
async def health():
    paper = desk.cfg.get("paper") or {}
    return {"ok": True, "authed": desk.authed, "observe_only": not bool(paper.get("enabled")), "paper": paper}


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
        return desk.update_setting(
            body.active,
            body.strategy,
            body.key,
            body.value,
            body.asset,
            paper_edge_basis=body.paper_edge_basis,
            paper_min_net_edge_cents=body.paper_min_net_edge_cents,
            paper_ignore_edge_gate=body.paper_ignore_edge_gate,
            paper_fade_model=body.paper_fade_model,
            paper_fade_trigger_cents=body.paper_fade_trigger_cents,
            weekend_timezone=body.weekend_timezone,
            weekend_feed_freshness_enabled=body.weekend_feed_freshness_enabled,
            weekend_feed_max_age_secs=body.weekend_feed_max_age_secs,
            paper_momentum_gate_enabled=body.paper_momentum_gate_enabled,
            meas_settlement_window=body.meas_settlement_window,
            meas_book_metrics=body.meas_book_metrics,
            meas_window_features=body.meas_window_features,
            meas_liquidation=body.meas_liquidation,
            meas_price_buckets=body.meas_price_buckets,
        )


@app.post("/api/settings/reset")
async def reset_settings():
    async with desk._lock:
        return desk.reset_settings()


@app.post("/api/journal/clear")
async def clear_journal():
    async with desk._lock:
        return desk.clear_journal()
