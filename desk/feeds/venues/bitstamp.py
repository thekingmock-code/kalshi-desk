"""Bitstamp public websocket (trades + order book)."""
from __future__ import annotations

import asyncio
import json

import websockets

from desk.feeds.venues.base import VenueAssetState, reconnect_loop, utc_ms

URL = "wss://ws.bitstamp.net"


class BitstampVenue:
    name = "bitstamp"

    async def start(
        self,
        stop: asyncio.Event,
        *,
        asset_pairs: dict[str, str],
        states: dict[str, VenueAssetState],
        on_trade: callable,
    ) -> None:
        channel_to_asset = {f"live_trades_{pair}": asset for asset, pair in asset_pairs.items()}
        book_channels = {f"order_book_{pair}": asset for asset, pair in asset_pairs.items()}

        async def once() -> None:
            async with websockets.connect(URL, ping_interval=20, ping_timeout=20) as ws:
                for ch in list(channel_to_asset.keys()) + list(book_channels.keys()):
                    await ws.send(json.dumps({"event": "bts:subscribe", "data": {"channel": ch}}))
                while not stop.is_set():
                    try:
                        raw = await asyncio.wait_for(ws.recv(), timeout=1.0)
                    except asyncio.TimeoutError:
                        continue
                    self._handle(raw, channel_to_asset, book_channels, states, on_trade)

        await reconnect_loop(stop, self.name, once)

    def _handle(self, raw: str, trade_map, book_map, states, on_trade) -> None:
        try:
            msg = json.loads(raw)
        except json.JSONDecodeError:
            return
        event = msg.get("event") or msg.get("channel")
        channel = msg.get("channel") or (msg.get("data") or {}).get("channel")
        data = msg.get("data") if isinstance(msg.get("data"), dict) else msg
        if not channel:
            return
        asset = trade_map.get(channel) or book_map.get(channel)
        if not asset:
            return
        st = states.get(asset)
        if not st:
            return
        now_ms = utc_ms()
        if channel.startswith("live_trades_"):
            price = _f(data.get("price") if isinstance(data, dict) else None)
            amount = _f(data.get("amount") if isinstance(data, dict) else None)
            if price and amount:
                st.last_trade = price
                st.mid = price
                st.last_tick_ts_ms = now_ms
                side_buy = str(data.get("type") or "").lower() == "0"
                on_trade(self.name, asset, price * amount, side_buy, now_ms / 1000.0)
        elif channel.startswith("order_book_"):
            bids = data.get("bids") if isinstance(data, dict) else None
            asks = data.get("asks") if isinstance(data, dict) else None
            if bids and asks:
                best_bid = max(_f(row[0]) or 0 for row in bids if row)
                best_ask = min(_f(row[0]) or 1e18 for row in asks if row)
                if best_bid > 0 and best_ask < 1e17:
                    st.bid, st.ask = best_bid, best_ask
                    st.update_mid_from_book()
                    b_d = sum(_f(r[1]) or 0 for r in bids[:3])
                    a_d = sum(_f(r[1]) or 0 for r in asks[:3])
                    st.record_depth(b_d + a_d, now_ms=now_ms)


def _f(v) -> float | None:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if x > 0 else None
