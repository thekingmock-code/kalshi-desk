"""Spot venue order-book imbalance (log-only)."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field


@dataclass
class VenueBook:
    bids: dict[float, float] = field(default_factory=dict)
    asks: dict[float, float] = field(default_factory=dict)
    last_ts: float = 0.0

    def apply_snapshot(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]], ts: float) -> None:
        self.bids = {p: s for p, s in bids if s > 0}
        self.asks = {p: s for p, s in asks if s > 0}
        self.last_ts = ts

    def apply_delta(self, bids: list[tuple[float, float]], asks: list[tuple[float, float]], ts: float) -> None:
        for p, s in bids:
            if s <= 0:
                self.bids.pop(p, None)
            else:
                self.bids[p] = s
        for p, s in asks:
            if s <= 0:
                self.asks.pop(p, None)
            else:
                self.asks[p] = s
        self.last_ts = ts


def _top3_depth(levels: dict[float, float], *, bids: bool) -> float:
    if not levels:
        return 0.0
    prices = sorted(levels.keys(), reverse=bids)
    return sum(levels[p] for p in prices[:3])


def _depth_within_bps(levels: dict[float, float], mid: float, bps: float, *, bids: bool) -> float:
    if not levels or mid <= 0:
        return 0.0
    band = mid * (bps / 10000.0)
    lo = mid - band if bids else mid
    hi = mid if bids else mid + band
    total = 0.0
    for p, s in levels.items():
        if s <= 0:
            continue
        if bids and lo <= p <= hi:
            total += s
        elif not bids and lo <= p <= hi:
            total += s
    return total


def _obi(bid_depth: float, ask_depth: float) -> float | None:
    if bid_depth <= 0 and ask_depth <= 0:
        return None
    denom = bid_depth + ask_depth
    if denom <= 0:
        return None
    return bid_depth / denom


def venue_metrics(book: VenueBook | None, mid: float | None) -> dict:
    if book is None or mid is None or mid <= 0:
        return {
            "bid_depth_top3": None,
            "ask_depth_top3": None,
            "bid_depth_50bps": None,
            "ask_depth_50bps": None,
            "obi_top3": None,
            "obi_50bps": None,
        }
    b3 = _top3_depth(book.bids, bids=True)
    a3 = _top3_depth(book.asks, bids=False)
    b50 = _depth_within_bps(book.bids, mid, 50.0, bids=True)
    a50 = _depth_within_bps(book.asks, mid, 50.0, bids=False)
    return {
        "bid_depth_top3": round(b3, 6),
        "ask_depth_top3": round(a3, 6),
        "bid_depth_50bps": round(b50, 6),
        "ask_depth_50bps": round(a50, 6),
        "obi_top3": None if _obi(b3, a3) is None else round(_obi(b3, a3), 4),
        "obi_50bps": None if _obi(b50, a50) is None else round(_obi(b50, a50), 4),
    }


@dataclass
class ObiPersistence:
    window_s: float = 10.0
    history: deque = field(default_factory=deque)

    def push(self, ts: float, obi_comb_top3: float | None) -> None:
        if obi_comb_top3 is None:
            return
        self.history.append((ts, obi_comb_top3))
        while self.history and ts - self.history[0][0] > self.window_s:
            self.history.popleft()

    def stats(self, current: float | None) -> tuple[float | None, int, bool]:
        if not self.history or current is None:
            return None, 0, False
        vals = [v for _, v in self.history]
        avg = sum(vals) / len(vals)
        flips = 0
        prev_side = None
        for v in vals:
            side = v > 0.5
            if prev_side is not None and side != prev_side:
                flips += 1
            prev_side = side
        same_side = (avg > 0.5 and current > 0.5) or (avg <= 0.5 and current <= 0.5)
        persistent = same_side and flips <= 1
        return round(avg, 4), flips, persistent


def combine_venues(cb: dict, kr: dict) -> dict:
    def _sum(a, b):
        if a is None and b is None:
            return None
        return (a or 0.0) + (b or 0.0)

    b3 = _sum(cb.get("bid_depth_top3"), kr.get("bid_depth_top3"))
    a3 = _sum(cb.get("ask_depth_top3"), kr.get("ask_depth_top3"))
    b50 = _sum(cb.get("bid_depth_50bps"), kr.get("bid_depth_50bps"))
    a50 = _sum(cb.get("ask_depth_50bps"), kr.get("ask_depth_50bps"))
    return {
        "obi_comb_top3": None if _obi(b3 or 0, a3 or 0) is None else round(_obi(b3 or 0, a3 or 0), 4),
        "obi_comb_50bps": None if _obi(b50 or 0, a50 or 0) is None else round(_obi(b50 or 0, a50 or 0), 4),
    }


def obi_agrees_side(obi_comb_top3: float | None, side: str | None) -> bool | None:
    if obi_comb_top3 is None or side not in ("UP", "DOWN"):
        return None
    if side == "UP":
        if obi_comb_top3 > 0.55:
            return True
        if obi_comb_top3 < 0.45:
            return False
        return None
    if obi_comb_top3 < 0.45:
        return True
    if obi_comb_top3 > 0.55:
        return False
    return None


def build_obi_snapshot(
    *,
    coinbase_book: VenueBook | None,
    kraken_book: VenueBook | None,
    coinbase_mid: float | None,
    kraken_mid: float | None,
    persistence: ObiPersistence,
    ts: float,
    entry_side: str | None = None,
) -> dict:
    cb = venue_metrics(coinbase_book, coinbase_mid)
    kr = venue_metrics(kraken_book, kraken_mid)
    cb_out = {f"coinbase_{k}": v for k, v in cb.items()}
    kr_out = {f"kraken_{k}": v for k, v in kr.items()}
    comb = combine_venues(cb, kr)
    obi_top3 = comb.get("obi_comb_top3")
    persistence.push(ts, obi_top3)
    avg, flips, pers = persistence.stats(obi_top3)
    snap = {
        **cb_out,
        **kr_out,
        **comb,
        "obi_avg_10s": avg,
        "obi_flips_10s": flips,
        "obi_persistent": pers,
        "obi_agrees_side": obi_agrees_side(obi_top3, entry_side),
    }
    return snap


def obi_bucket(obi: float | None) -> str:
    if obi is None:
        return "unknown"
    if obi < 0.35:
        return "<0.35"
    if obi < 0.45:
        return "0.35-0.45"
    if obi < 0.55:
        return "0.45-0.55"
    if obi < 0.65:
        return "0.55-0.65"
    return ">0.65"
