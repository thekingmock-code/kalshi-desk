"""Coinbase Advanced Trade ticker and market trades."""
from __future__ import annotations

import asyncio
import json
from collections.abc import Callable

import websockets

URL = "wss://advanced-trade-ws.coinbase.com"

OnPrice = Callable[[str, float, float], None]
OnTrade = Callable[[str, float, bool, float], None]
OnBook = Callable[[str, list[tuple[float, float]], list[tuple[float, float]], bool, float], None]


async def stream(
    products: dict[str, str],
    on_price: OnPrice,
    on_trade: OnTrade,
    stop: asyncio.Event,
    on_book: OnBook | None = None,
) -> None:
    """products maps asset -> product id (BTC-USD). Reconnects until stop is set.

    market_trades `side` is the taker side (BUY / SELL), unlike the Exchange REST
    API where `side` is the maker.
    """
    ids = list(products.values())
    by_product = {pid: asset for asset, pid in products.items()}
    while not stop.is_set():
        try:
            async with websockets.connect(URL, ping_interval=20, ping_timeout=20) as ws:
                channels = ["ticker", "market_trades"]
                if on_book is not None:
                    channels.append("level2")
                for channel in channels:
                    await ws.send(json.dumps({"type": "subscribe", "product_ids": ids, "channel": channel}))
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    _handle(raw, by_product, on_price, on_trade, on_book)
        except Exception as exc:
            if stop.is_set():
                return
            print(f"Coinbase feed: {exc}; reconnecting")
            await asyncio.sleep(2)


def _handle(
    raw: str,
    by_product: dict[str, str],
    on_price: OnPrice,
    on_trade: OnTrade,
    on_book: OnBook | None,
) -> None:
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
    elif channel in ("level2", "l2_data") and on_book:
        for ev in data.get("events") or []:
            pid = ev.get("product_id")
            asset = by_product.get(pid)
            if not asset:
                continue
            ev_type = str(ev.get("type") or "").lower()
            snapshot = ev_type == "snapshot"
            bids: list[tuple[float, float]] = []
            asks: list[tuple[float, float]] = []
            if snapshot:
                bids = _levels(ev.get("bids") or [])
                asks = _levels(ev.get("asks") or [])
            else:
                for ch in ev.get("updates") or ev.get("changes") or []:
                    if isinstance(ch, (list, tuple)) and len(ch) >= 3:
                        side = str(ch[0]).lower()
                        price, size = _f(ch[1]), _f(ch[2])
                    elif isinstance(ch, dict):
                        side = str(ch.get("side") or "").lower()
                        price = _f(ch.get("price_level") or ch.get("price"))
                        size = _f(ch.get("new_quantity") or ch.get("size") or ch.get("quantity"))
                    else:
                        continue
                    if price is None:
                        continue
                    pair = (price, size or 0.0)
                    if side.startswith("b"):
                        bids.append(pair)
                    else:
                        asks.append(pair)
            if bids or asks or snapshot:
                on_book(asset, bids, asks, snapshot, now)


def _levels(rows) -> list[tuple[float, float]]:
    out: list[tuple[float, float]] = []
    for row in rows or []:
        if isinstance(row, (list, tuple)) and len(row) >= 2:
            p, s = _f(row[0]), _f(row[1])
        elif isinstance(row, dict):
            p = _f(row.get("price") or row.get("price_level"))
            s = _f(row.get("size") or row.get("new_quantity") or row.get("quantity"))
        else:
            continue
        if p is not None and s is not None:
            out.append((p, s))
    return out


def _f(value) -> float | None:
    try:
        num = float(value)
    except (TypeError, ValueError):
        return None
    return num if num > 0 else None
