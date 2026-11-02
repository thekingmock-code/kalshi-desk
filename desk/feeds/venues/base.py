"""Shared spot venue state and reconnect helpers."""
from __future__ import annotations

import asyncio
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Protocol


def utc_ms(ts: float | None = None) -> float:
    return (ts if ts is not None else time.time()) * 1000.0


@dataclass
class VenueAssetState:
    """Latest normalized quote for one venue × asset."""

    mid: float | None = None
    last_trade: float | None = None
    last_tick_ts_ms: float | None = None
    bid: float | None = None
    ask: float | None = None
    depth_top_n: float = 0.0
    _depth_hist: deque = field(default_factory=deque)

    def record_depth(self, depth: float, *, now_ms: float, window_ms: float = 60_000.0) -> None:
        self.depth_top_n = max(0.0, float(depth))
        self._depth_hist.append((now_ms, self.depth_top_n))
        while self._depth_hist and now_ms - self._depth_hist[0][0] > window_ms:
            self._depth_hist.popleft()

    def depth_avg(self, *, now_ms: float, window_ms: float = 60_000.0) -> float:
        vals = [d for t, d in self._depth_hist if now_ms - t <= window_ms]
        if not vals:
            return self.depth_top_n
        return sum(vals) / len(vals)

    def update_mid_from_book(self) -> None:
        if self.bid is not None and self.ask is not None and self.bid > 0 and self.ask > 0:
            self.mid = (self.bid + self.ask) / 2.0


class SpotVenue(Protocol):
    name: str

    async def start(
        self,
        stop: asyncio.Event,
        *,
        asset_pairs: dict[str, str],
        states: dict[str, VenueAssetState],
        on_trade: callable,
    ) -> None: ...


async def reconnect_loop(
    stop: asyncio.Event,
    name: str,
    connect_once: callable,
) -> None:
    """Exponential backoff 1s–30s, re-subscribe inside connect_once."""
    delay = 1.0
    while not stop.is_set():
        try:
            await connect_once()
            delay = 1.0
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            if stop.is_set():
                return
            print(f"{name} feed: {exc}; reconnect in {delay:.0f}s")
            await asyncio.sleep(delay)
            delay = min(30.0, delay * 2.0)
