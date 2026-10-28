"""Kalshi book / quote metrics from polled orderbooks (log-only)."""
from __future__ import annotations

import json
from collections import deque
from dataclasses import dataclass, field


@dataclass
class BookMetricsState:
    quote_changes: deque = field(default_factory=lambda: deque(maxlen=500))
    last_sig: str | None = None
    last_composite_move_ts: float | None = None
    last_quote_change_ts: float | None = None
    quote_lag_ms: float | None = None
    trades: deque = field(default_factory=lambda: deque(maxlen=400))

    def on_book(self, now: float, book: dict) -> None:
        sig = json.dumps(
            {
                "yb": book.get("yes_bid"),
                "ya": book.get("yes_ask"),
                "nb": book.get("no_bid"),
                "na": book.get("no_ask"),
                "dy": book.get("depth_yes_top3"),
                "dn": book.get("depth_no_top3"),
            },
            sort_keys=True,
        )
        if self.last_sig is not None and sig != self.last_sig:
            self.quote_changes.append(now)
            self.last_quote_change_ts = now
            if self.last_composite_move_ts is not None:
                self.quote_lag_ms = (now - self.last_composite_move_ts) * 1000.0
        self.last_sig = sig

    def on_composite_move(self, now: float, delta_usd: float, threshold: float) -> None:
        if abs(delta_usd) >= threshold:
            self.last_composite_move_ts = now
            self.quote_lag_ms = None

    def on_trade(self, ts: float, contracts: float, taker_side: str | None) -> None:
        self.trades.append((ts, contracts, taker_side))

    def snapshot(self, now: float, book: dict) -> dict:
        yes_d = float(book.get("depth_yes_top3") or 0)
        no_d = float(book.get("depth_no_top3") or 0)
        tot = yes_d + no_d
        imb = None if tot <= 0 else yes_d / tot
        cutoff = now - 10.0
        updates_10s = sum(1 for t in self.quote_changes if t >= cutoff)
        vol_60 = 0.0
        taker_yes = taker_no = 0.0
        for ts, c, side in self.trades:
            if ts < now - 60:
                continue
            vol_60 += c
            if side == "yes":
                taker_yes += c
            elif side == "no":
                taker_no += c
        taker_side = None
        if taker_yes > taker_no:
            taker_side = "yes"
        elif taker_no > taker_yes:
            taker_side = "no"
        return {
            "depth_yes_top3": yes_d or None,
            "depth_no_top3": no_d or None,
            "book_imbalance": imb,
            "quote_updates_10s": updates_10s,
            "quote_lag_ms": self.quote_lag_ms,
            "trade_volume_60s": vol_60 or None,
            "taker_side_60s": taker_side,
        }
