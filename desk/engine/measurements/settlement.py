"""Settlement-minute window tracker (log-only)."""
from __future__ import annotations

import math
from typing import Sequence

from desk.engine.model import norm_cdf

SETTLE_WINDOW_SECS = 60.0


def window_avg_so_far(
    samples: Sequence[tuple[float, float]],
    close_ts: float | None,
    now: float,
    ref: float | None,
) -> float | None:
    if close_ts is None or ref is None:
        return None
    start = close_ts - SETTLE_WINDOW_SECS
    if now < start:
        return None
    vals = [px for ts, px in samples if start <= ts <= now]
    if not vals:
        return ref
    return sum(vals) / len(vals)


def locked_frac(close_ts: float | None, now: float) -> float | None:
    if close_ts is None:
        return None
    start = close_ts - SETTLE_WINDOW_SECS
    if now < start:
        return None
    elapsed = min(SETTLE_WINDOW_SECS, max(0.0, now - start))
    return elapsed / SETTLE_WINDOW_SECS


def p_up_avgmodel(
    *,
    ref: float | None,
    strike: float | None,
    move_1m: float | None,
    window_avg: float | None,
    locked: float | None,
) -> float | None:
    if ref is None or strike is None or window_avg is None or locked is None:
        return None
    if locked >= 1.0 - 1e-9:
        return 1.0 if window_avg >= strike else 0.0
    rem = (1.0 - locked) * SETTLE_WINDOW_SECS
    exp_avg = locked * window_avg + (1.0 - locked) * ref
    move = move_1m or 0.0
    if move <= 0:
        return 1.0 if exp_avg >= strike else 0.0
    sigma = move * math.sqrt(rem / 60.0)
    if sigma <= 0:
        return 1.0 if exp_avg >= strike else 0.0
    z = max(-8.0, min(8.0, (exp_avg - strike) / sigma))
    return norm_cdf(z)


def settlement_snapshot(
    *,
    samples: Sequence[tuple[float, float]],
    close_ts: float | None,
    now: float,
    ref: float | None,
    strike: float | None,
    move_1m: float | None,
    p_up: float | None,
) -> dict:
    wavg = window_avg_so_far(samples, close_ts, now, ref)
    lf = locked_frac(close_ts, now)
    pup_avg = p_up_avgmodel(ref=ref, strike=strike, move_1m=move_1m, window_avg=wavg, locked=lf)
    avg_vs = None if wavg is None or strike is None else wavg - strike
    return {
        "window_avg_so_far": wavg,
        "locked_frac": lf,
        "avg_vs_strike": avg_vs,
        "p_up": p_up,
        "p_up_avgmodel": pup_avg,
    }
