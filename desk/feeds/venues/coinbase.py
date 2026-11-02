"""Coinbase venue adapter (wraps existing stream)."""
from __future__ import annotations

import asyncio

from desk.feeds import coinbase as cb_feed
from desk.feeds.venues.base import VenueAssetState, reconnect_loop, utc_ms


class CoinbaseVenue:
    name = "coinbase"

    async def start(
        self,
        stop: asyncio.Event,
        *,
        asset_pairs: dict[str, str],
        states: dict[str, VenueAssetState],
        on_trade: callable,
        on_book_extra: callable | None = None,
    ) -> None:
        async def once() -> None:
            def on_price(asset: str, price: float, ts: float) -> None:
                st = states.get(asset)
                if not st:
                    return
                st.mid = price
                st.last_tick_ts_ms = utc_ms(ts)

            def on_trade_cb(asset: str, usd: float, is_buy: bool, ts: float) -> None:
                st = states.get(asset)
                if st:
                    st.last_trade = usd
                    st.last_tick_ts_ms = utc_ms(ts)
                on_trade(self.name, asset, usd, is_buy, ts)

            def on_book(asset: str, bids, asks, snapshot: bool, ts: float) -> None:
                del snapshot
                st = states.get(asset)
                if not st:
                    return
                if bids:
                    st.bid = max(p for p, _ in bids)
                if asks:
                    st.ask = min(p for p, _ in asks)
                st.update_mid_from_book()
                b_d = sum(s for _, s in sorted(bids, key=lambda x: -x[0])[:3]) if bids else 0.0
                a_d = sum(s for _, s in sorted(asks, key=lambda x: x[0])[:3]) if asks else 0.0
                st.record_depth(b_d + a_d, now_ms=utc_ms(ts))
                if on_book_extra:
                    on_book_extra(asset, bids, asks, snapshot, ts)

            await cb_feed.stream(asset_pairs, on_price, on_trade_cb, stop, on_book)

        await reconnect_loop(stop, self.name, once)
