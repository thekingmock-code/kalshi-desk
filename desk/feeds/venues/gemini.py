"""Gemini public marketdata websocket (one URL per pair)."""
from __future__ import annotations

import asyncio
import json

import websockets

from desk.feeds.venues.base import VenueAssetState, reconnect_loop, utc_ms


class GeminiVenue:
    name = "gemini"

    async def start(
        self,
        stop: asyncio.Event,
        *,
        asset_pairs: dict[str, str],
        states: dict[str, VenueAssetState],
        on_trade: callable,
    ) -> None:
        if not asset_pairs:
            while not stop.is_set():
                await asyncio.sleep(1.0)
            return

        async def once() -> None:
            tasks = [
                asyncio.create_task(
                    self._stream_pair(stop, asset, pair.lower(), states, on_trade),
                    name=f"gemini-{pair}",
                )
                for asset, pair in asset_pairs.items()
            ]
            try:
                await asyncio.gather(*tasks)
            finally:
                for t in tasks:
                    t.cancel()

        await reconnect_loop(stop, self.name, once)

    async def _stream_pair(
        self,
        stop: asyncio.Event,
        asset: str,
        pair: str,
        states: dict[str, VenueAssetState],
        on_trade: callable,
    ) -> None:
        url = f"wss://api.gemini.com/v1/marketdata/{pair}"
        st = states[asset]
        bids: dict[float, float] = {}
        asks: dict[float, float] = {}
        while not stop.is_set():
            try:
                async with websockets.connect(url, ping_interval=20, ping_timeout=20) as ws:
                    while not stop.is_set():
                        try:
                            raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                        except asyncio.TimeoutError:
                            continue
                        now_ms = utc_ms()
                        try:
                            events = json.loads(raw)
                        except json.JSONDecodeError:
                            continue
                        if not isinstance(events, list):
                            events = [events]
                        for ev in events:
                            if not isinstance(ev, dict):
                                continue
                            typ = ev.get("type")
                            if typ == "trade":
                                price = _f(ev.get("price"))
                                qty = _f(ev.get("amount"))
                                if price and qty:
                                    st.last_trade = price
                                    st.mid = price
                                    st.last_tick_ts_ms = now_ms
                                    side = str(ev.get("makerSide") or "").lower()
                                    on_trade(self.name, asset, price * qty, side == "ask", now_ms / 1000.0)
                            elif typ == "change":
                                price = _f(ev.get("price"))
                                rem = _f(ev.get("remaining"))
                                side = str(ev.get("side") or "").lower()
                                if price is None:
                                    continue
                                book = bids if side == "bid" else asks
                                if rem is None or rem <= 0:
                                    book.pop(price, None)
                                else:
                                    book[price] = rem
                                if bids and asks:
                                    st.bid = max(bids.keys())
                                    st.ask = min(asks.keys())
                                    st.update_mid_from_book()
                                    b_d = sum(sorted(bids.values(), reverse=True)[:3])
                                    a_d = sum(sorted(asks.values())[:3])
                                    st.record_depth(b_d + a_d, now_ms=now_ms)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                if stop.is_set():
                    return
                print(f"Gemini {pair}: {exc}; reconnecting")
                await asyncio.sleep(2.0)


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None
