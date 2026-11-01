"""Composite / strike / TWAP boundary series for Features tab chart."""
from __future__ import annotations

import math
import random
from typing import Any


def _required_spot(strike: float, window: list[float], window_len: int = 60) -> float:
    ticks_passed = len(window)
    ticks_remaining = max(1, window_len - ticks_passed)
    target_total = strike * window_len
    sum_passed = sum(window)
    return (target_total - sum_passed) / ticks_remaining


def series_from_composite_points(
    points: list[dict],
    *,
    strike: float | None,
    settlement_secs: int = 60,
) -> dict[str, Any]:
    """Build candle + overlay series from desk chart_points ({t, c, s, ...})."""
    if not points:
        return {"ok": False, "source": "live", "rows": []}
    if strike is None:
        for pt in reversed(points):
            s = pt.get("s")
            if s is not None and float(s) > 0:
                strike = float(s)
                break
    if strike is None:
        return {"ok": False, "source": "live", "rows": []}

    rows: list[dict] = []
    window: list[float] = []
    prev_c: float | None = None
    t0 = float(points[0].get("t") or 0)
    last_t = -1
    for pt in points:
        raw_t = pt.get("t")
        if raw_t is not None:
            t = int(round(float(raw_t) - t0))
        else:
            t = len(rows)
        if t <= last_t:
            t = last_t + 1
        last_t = t
        c = float(pt["c"])
        window.append(c)
        if len(window) > settlement_secs:
            window.pop(0)
        req = _required_spot(strike, window, settlement_secs)
        wick = max(0.5, abs(c - (prev_c or c)) * 0.3)
        rows.append(
            {
                "time": t,
                "open": prev_c if prev_c is not None else c,
                "high": c + wick,
                "low": c - wick,
                "close": c,
                "strike": strike,
                "required_spot": req,
                "signal": "none",
            }
        )
        prev_c = c
    return {
        "ok": True,
        "source": "live",
        "asset": None,
        "strike": strike,
        "rows": rows,
    }


def mock_arbitrage_series(*, seed: int = 42, timesteps: int = 120, strike_price: float = 65000.0) -> dict[str, Any]:
    """Deterministic demo series (same logic as scripts/generate_trading_chart.py, no numpy)."""
    rng = random.Random(seed)
    base_time = 1793782400
    coinbase = 65010.0
    prices_cb: list[float] = []
    for _ in range(timesteps):
        coinbase += rng.gauss(0.2, 3.0)
        prices_cb.append(coinbase)
    composite: list[float] = []
    for i, cb in enumerate(prices_cb):
        kr = cb + rng.gauss(0, 1.5)
        bs = cb + rng.gauss(0, 2.0)
        composite.append((cb + kr + bs) / 3.0)

    rows: list[dict] = []
    window: list[float] = []
    for t in range(timesteps):
        current_time = base_time + t
        current_spot = composite[t]
        window.append(current_spot)
        if len(window) > 60:
            window.pop(0)
        req = _required_spot(strike_price, window, 60)

        if t > 5:
            recent = composite[max(0, t - 15) : t + 1]
            rets = [(recent[i] - recent[i - 1]) / recent[i - 1] for i in range(1, len(recent))]
            vol = (sum((r - sum(rets) / len(rets)) ** 2 for r in rets) / len(rets)) ** 0.5 if rets else 0.0001
        else:
            vol = 0.0002
        ticks_remaining = max(1, 60 - len(window))
        denom = vol * current_spot * math.sqrt(ticks_remaining)
        sigma_distance = abs(current_spot - req) / denom if denom > 0 else 0.0

        signal = "none"
        if 0.5 <= sigma_distance <= 1.5:
            if t > 2 and composite[t] > composite[t - 2] and current_spot < strike_price:
                signal = "buy"
            elif t > 2 and composite[t] < composite[t - 2] and current_spot > strike_price:
                signal = "sell"

        rows.append(
            {
                "time": current_time,
                "open": current_spot - rng.uniform(1, 3),
                "high": current_spot + rng.uniform(2, 5),
                "low": current_spot - rng.uniform(2, 5),
                "close": current_spot,
                "strike": strike_price,
                "required_spot": req if t < 60 else strike_price,
                "signal": signal,
            }
        )
    return {"ok": True, "source": "demo", "asset": None, "strike": strike_price, "rows": rows}


def build_arbitrage_chart_payload(
    *,
    asset: str,
    chart_points: list[dict],
    strike: float | None,
) -> dict[str, Any]:
    """Main dashboard chart: live composite ticks only (no demo fallback)."""
    live = series_from_composite_points(chart_points, strike=strike)
    live["asset"] = asset
    live["live_points"] = len(chart_points)
    if live.get("ok"):
        return live
    if strike is None:
        live["note"] = "Waiting for market strike on this 15m window."
    elif not chart_points:
        live["note"] = "Waiting for live composite ticks (feeds + open market)."
    else:
        live["note"] = "Live chart unavailable for this window."
    return live
