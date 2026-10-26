"""Settlement, effective time, fair probability, and fees."""
from __future__ import annotations

import math
from decimal import Decimal, ROUND_CEILING


def eff_seconds(
    secs: float,
    *,
    break_at: float = 60,
    offset: float = 40,
    cubic_div: float = 10800,
    floor: float = 0.5,
) -> float:
    """Seconds that still move the 60s settlement average."""
    if secs >= break_at:
        raw = secs - offset
    else:
        raw = (secs ** 3) / cubic_div
    return max(raw, floor)


def resolves_yes(close_avg: float, open_avg: float) -> bool:
    """YES if the closing minute average is at least the opening minute average. Ties are YES."""
    return close_avg >= open_avg


def norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fair_up(ref: float, strike: float, move_1m: float, secs_left: float, model: dict) -> tuple[float | None, float, float]:
    """Return (p_up, sigma_T, effS). p_up is None when vol is not usable."""
    eff_s = eff_seconds(
        max(secs_left, 0.0),
        break_at=float(model["effs_break"]),
        offset=float(model["effs_offset"]),
        cubic_div=float(model["effs_cubic_div"]),
        floor=float(model["effs_floor"]),
    )
    if move_1m <= 0 or strike <= 0 or ref <= 0:
        return None, 0.0, eff_s
    sigma_t = move_1m * math.sqrt(eff_s / 60.0)
    if sigma_t <= 0:
        return None, sigma_t, eff_s
    z = max(-8.0, min(8.0, (ref - strike) / sigma_t))
    return norm_cdf(z), sigma_t, eff_s


def fee_dollars(contracts: float, price: float, rate: float) -> float:
    """Taker fee rounded up to the next cent: ceil(rate * C * P * (1-P))."""
    if contracts <= 0 or price <= 0 or price >= 1 or rate <= 0:
        return 0.0
    raw = (
        Decimal(str(rate))
        * Decimal(str(contracts))
        * Decimal(str(price))
        * (Decimal("1") - Decimal(str(price)))
    )
    cents = (raw * Decimal("100")).to_integral_value(rounding=ROUND_CEILING)
    return float(cents / Decimal("100"))


def composite_price(
    feeds: list[tuple[str, float, float]],
    now: float,
    stale_secs: float,
) -> tuple[float | None, list[str]]:
    """Average fresh last prices. Drop any print older than stale_secs."""
    fresh = [(name, px) for name, px, ts in feeds if px and px > 0 and now - ts <= stale_secs]
    if not fresh:
        return None, []
    names = [name for name, _ in fresh]
    return sum(px for _, px in fresh) / len(fresh), names


def move_1m_from_returns(stdev_per_sec: float | None, price: float | None) -> float | None:
    if stdev_per_sec is None or price is None or price <= 0:
        return None
    return price * stdev_per_sec * math.sqrt(60.0)


def log_return_stdev(samples: list[tuple[float, float]], now: float, window: float) -> float | None:
    pts = [px for ts, px in samples if now - window <= ts <= now and px > 0]
    if len(pts) < 3:
        return None
    rets = [math.log(b / a) for a, b in zip(pts, pts[1:]) if a > 0 and b > 0]
    if len(rets) < 2:
        return None
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / (len(rets) - 1)
    return math.sqrt(var)
