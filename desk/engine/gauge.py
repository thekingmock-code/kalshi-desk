"""Distance-to-strike gauge for the dashboard."""
from __future__ import annotations

import math


def build_gauge(
    *,
    composite: float | None,
    strike: float | None,
    move_1m: float | None,
    baseline_move: float | None,
    secs_left: float | None,
    favored: str | None,
) -> dict:
    if composite is None or strike is None or strike <= 0:
        return {"ok": False, "label": "no data"}
    gap_usd = round(composite - strike, 2)
    gap_pct = gap_usd / strike
    minutes_left = None
    sigma = None
    if secs_left is not None and secs_left > 0 and move_1m and move_1m > 0:
        minutes_left = max(secs_left / 60.0, 1.0 / 60.0)
        denom = move_1m * math.sqrt(minutes_left)
        if denom > 0:
            sigma = gap_usd / denom
    required_usd = -gap_usd
    mult_1m = None
    if move_1m and move_1m > 0:
        mult_1m = abs(required_usd) / move_1m
    vol_mult = None
    if baseline_move and baseline_move > 0 and move_1m:
        vol_mult = move_1m / baseline_move
    bar_pos = None if sigma is None else max(-3.0, min(3.0, sigma))
    side = favored
    if side is None:
        side = "UP" if gap_usd >= 0 else "DOWN"
    return {
        "ok": True,
        "gap_usd": gap_usd,
        "gap_pct": round(gap_pct * 100, 3),
        "sigma": None if sigma is None else round(sigma, 2),
        "bar_pos": bar_pos,
        "required_usd": round(required_usd, 2),
        "required_abs_usd": round(abs(required_usd), 2),
        "secs_left": secs_left,
        "mult_1m": None if mult_1m is None else round(mult_1m, 2),
        "vol_ratio": vol_mult,
        "favored": side,
        "composite": composite,
        "strike": strike,
    }
