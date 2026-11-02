"""Multi-venue composite (depth-weighted) with log-only diagnostics."""
from __future__ import annotations

import logging
import statistics
import time
from typing import Any

from desk.feeds.venues.base import VenueAssetState

log = logging.getLogger("desk.composite")


def _median(vals: list[float]) -> float | None:
    if not vals:
        return None
    return float(statistics.median(vals))


def build_feeds_from_states(
    states: dict[str, VenueAssetState],
    *,
    now: float,
) -> list[tuple[str, float, float]]:
    """Legacy feed tuples (name, mid, ts_sec) for composite_price fallback."""
    out: list[tuple[str, float, float]] = []
    for name, st in states.items():
        if st.mid is None or st.mid <= 0:
            continue
        ts = (st.last_tick_ts_ms or now * 1000.0) / 1000.0
        out.append((name, st.mid, ts))
    return out


def compute_composite(
    states: dict[str, VenueAssetState],
    *,
    now: float | None = None,
    composite_cfg: dict | None = None,
    legacy_stale_secs: float = 5.0,
) -> tuple[float | None, list[str], dict[str, Any]]:
    """
    Weighted mean by rolling 60s depth; equal-weight fallback if no depth.
    Returns (price, venue_names_used, diagnostics).
    """
    now = now if now is not None else time.time()
    now_ms = now * 1000.0
    cfg = composite_cfg or {}
    drop_stale = bool(cfg.get("drop_stale_venues", False))
    stale_ms = float(cfg.get("stale_ms", 5000))
    window_ms = float(cfg.get("depth_window_secs", 60)) * 1000.0

    candidates: list[tuple[str, float, float, float]] = []
    for name, st in states.items():
        if st.mid is None or st.mid <= 0:
            continue
        age_ms = now_ms - (st.last_tick_ts_ms or 0)
        if drop_stale and age_ms > stale_ms:
            continue
        if not drop_stale and age_ms > legacy_stale_secs * 1000.0:
            pass
        depth_w = st.depth_avg(now_ms=now_ms, window_ms=window_ms)
        if depth_w <= 0:
            depth_w = 1.0
        candidates.append((name, st.mid, depth_w, age_ms))

    diag: dict[str, Any] = {"venues": {}, "median": None, "weights": {}}
    if not candidates:
        return None, [], diag

    mids = [c[1] for c in candidates]
    total_w = sum(c[2] for c in candidates)
    if total_w <= 0:
        price = sum(mids) / len(mids)
        weights = {c[0]: 1.0 / len(candidates) for c in candidates}
    else:
        weights = {c[0]: c[2] / total_w for c in candidates}
        price = sum(c[1] * weights[c[0]] for c in candidates)

    med = _median(mids)
    diag["median"] = med
    diag["weights"] = weights
    for name, mid, _w, age_ms in candidates:
        dev = mid - price
        diag["venues"][name] = {
            "mid": mid,
            "age_ms": round(age_ms, 1),
            "deviation_usd": round(dev, 4),
            "deviation_bps": round((dev / price) * 10000, 2) if price else None,
        }

    names = [c[0] for c in candidates]
    return price, names, diag


def log_trade_deviations(
    asset: str,
    composite: float | None,
    diag: dict[str, Any],
    *,
    trigger_venue: str | None = None,
) -> None:
    if composite is None:
        return
    parts = []
    for name, row in sorted((diag.get("venues") or {}).items()):
        parts.append(
            f"{name} px={row['mid']:.2f} age={row['age_ms']:.0f}ms "
            f"dev={row['deviation_usd']:+.2f} ({row.get('deviation_bps')}bps)"
        )
    med = diag.get("median")
    extra = f" trigger={trigger_venue}" if trigger_venue else ""
    log.info(
        "composite %s=%.4f median=%s n=%d%s | %s",
        asset,
        composite,
        f"{med:.4f}" if med is not None else "—",
        len(parts),
        extra,
        " · ".join(parts),
    )
