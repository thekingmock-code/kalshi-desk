"""Kraken WebSocket v2 ticker and trades."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import websockets

URL = "wss://ws.kraken.com/v2"

OnPrice = Callable[[str, float, float], None]
OnTrade = Callable[[str, float, bool, float], None]


async def stream(symbols: dict[str, str], on_price: OnPrice, on_trade: OnTrade, stop: asyncio.Event) -> None:
    """symbols maps asset -> Kraken symbol (BTC/USD). Trade `side` is the taker side."""
    names = list(symbols.values())
    by_symbol = {sym: asset for asset, sym in symbols.items()}
    while not stop.is_set():
        try:
            async with websockets.connect(URL, ping_interval=20, ping_timeout=20) as ws:
                await ws.send(json.dumps({"method": "subscribe", "params": {"channel": "ticker", "symbol": names}}))
                await ws.send(
                    json.dumps({"method": "subscribe", "params": {"channel": "trade", "symbol": names, "snapshot": False}})
                )
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    _handle(raw, by_symbol, on_price, on_trade)
        except Exception as exc:
            if stop.is_set():
                return
            print(f"Kraken feed: {exc}; reconnecting")
            await asyncio.sleep(2)


def _handle(raw: str, by_symbol: dict[str, str], on_price: OnPrice, on_trade: OnTrade) -> None:
    import time

    data = json.loads(raw)
    channel = data.get("channel")
    now = time.time()
    if channel == "ticker":
        for row in data.get("data") or []:
            asset = by_symbol.get(row.get("symbol"))
            price = _f(row.get("last"))
            if asset and price:
                on_price(asset, price, now)
    elif channel == "trade":
        for row in data.get("data") or []:
            asset = by_symbol.get(row.get("symbol"))
            price = _f(row.get("price"))
            qty = _f(row.get("qty") if row.get("qty") is not None else row.get("volume"))
            if not asset or not price or not qty:
                continue
            side = str(row.get("side") or "").lower()
            on_trade(asset, price * qty, side == "buy", now)


def _f(value) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None
