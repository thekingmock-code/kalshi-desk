"""Coinbase Advanced Trade ticker and market trades."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import websockets

URL = "wss://advanced-trade-ws.coinbase.com"

OnPrice = Callable[[str, float, float], None]
OnTrade = Callable[[str, float, bool, float], None]


async def stream(products: dict[str, str], on_price: OnPrice, on_trade: OnTrade, stop: asyncio.Event) -> None:
    """products maps asset -> product id (BTC-USD). Reconnects until stop is set.

    market_trades `side` is the taker side (BUY / SELL), unlike the Exchange REST
    API where `side` is the maker.
    """
    ids = list(products.values())
    by_product = {pid: asset for asset, pid in products.items()}
    while not stop.is_set():
        try:
            async with websockets.connect(URL, ping_interval=20, ping_timeout=20) as ws:
                for channel in ("ticker", "market_trades"):
                    await ws.send(json.dumps({"type": "subscribe", "product_ids": ids, "channel": channel}))
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    _handle(raw, by_product, on_price, on_trade)
        except Exception as exc:
            if stop.is_set():
                return
            print(f"Coinbase feed: {exc}; reconnecting")
            await asyncio.sleep(2)


def _handle(raw: str, by_product: dict[str, str], on_price: OnPrice, on_trade: OnTrade) -> None:
    import time

    data = json.loads(raw)
    channel = data.get("channel")
    now = time.time()
    if channel == "ticker":
        for ev in data.get("events") or []:
            for tick in ev.get("tickers") or []:
                asset = by_product.get(tick.get("product_id"))
                price = _f(tick.get("price"))
                if asset and price:
                    on_price(asset, price, now)
    elif channel == "market_trades":
        for ev in data.get("events") or []:
            for trade in ev.get("trades") or []:
                asset = by_product.get(trade.get("product_id"))
                price = _f(trade.get("price"))
                size = _f(trade.get("size"))
                if not asset or not price or not size:
                    continue
                side = str(trade.get("side") or "").upper()
                on_trade(asset, price * size, side == "BUY", now)


def _f(value) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None
