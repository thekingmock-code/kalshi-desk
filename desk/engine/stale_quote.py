"""Stale Kalshi quote vs spot fair (arb hard gate + log-only elsewhere)."""
from __future__ import annotations

from typing import Any

from desk.engine.model import fair_up


def _lookup_price(samples: list[tuple[float, float]], target_ts: float) -> float | None:
    prior = None
    for ts, px in samples:
        if ts <= target_ts:
            prior = px
    return prior


def _lookup_mid(history: list[tuple[float, float, float | None]], target_ts: float, idx: int) -> float | None:
    """idx 1 = yes mid, 2 = no mid in tuple (ts, yes, no)."""
    prior = None
    for row in history:
        ts = row[0]
        if ts <= target_ts:
            prior = row[idx]
    return prior


def _fair_cents(p_side: float | None) -> float | None:
    if p_side is None:
        return None
    return p_side * 100.0


def _prob_at_composite(
    *,
    composite: float | None,
    strike: float | None,
    move_1m: float | None,
    secs_left: float | None,
    model_cfg: dict,
) -> float | None:
    if composite is None or strike is None or secs_left is None or move_1m is None:
        return None
    p_up, _, _ = fair_up(composite, strike, move_1m, secs_left, model_cfg)
    return p_up


def composite_move_usd(
    samples: list[tuple[float, float]], now: float, price: float | None, lookback_s: float
) -> float | None:
    if price is None:
        return None
    prior = _lookup_price(samples, now - lookback_s)
    if prior is None:
        return None
    return abs(price - prior)


def evaluate_side_stale(
    *,
    side: str,
    p_up_now: float | None,
    yes_mid_now: float | None,
    no_mid_now: float | None,
    samples: list[tuple[float, float]],
    mid_history: list[tuple[float, float, float | None]],
    now: float,
    strike: float | None,
    move_1m: float | None,
    secs_left: float | None,
    model_cfg: dict,
    lookback_s: float,
    min_fair_move_c: float,
    min_stale_gap_c: float,
    max_repriced_frac: float,
    composite_move_usd_val: float | None,
    min_composite_move_usd: float,
) -> dict[str, Any]:
    mid_now = yes_mid_now if side == "UP" else no_mid_now
    p_now = p_up_now if side == "UP" else (None if p_up_now is None else 1.0 - p_up_now)
    fair_now = _fair_cents(p_now)
    mid_now_c = None if mid_now is None else mid_now * 100.0

    target = now - lookback_s
    comp_ref = _lookup_price(samples, target)
    secs_ref = None if secs_left is None else secs_left + lookback_s
    p_up_ref = _prob_at_composite(
        composite=comp_ref,
        strike=strike,
        move_1m=move_1m,
        secs_left=secs_ref,
        model_cfg=model_cfg,
    )
    p_ref = p_up_ref if side == "UP" else (None if p_up_ref is None else 1.0 - p_up_ref)
    fair_ref = _fair_cents(p_ref)
    mid_idx = 1 if side == "UP" else 2
    mid_ref = _lookup_mid(mid_history, target, mid_idx)
    mid_ref_c = None if mid_ref is None else mid_ref * 100.0

    fair_move_c = None
    mid_move_c = None
    stale_gap_c = None
    repriced_frac = None
    if fair_now is not None and fair_ref is not None:
        fair_move_c = fair_now - fair_ref
    if mid_now_c is not None and mid_ref_c is not None:
        mid_move_c = mid_now_c - mid_ref_c
    if fair_now is not None and mid_now_c is not None:
        stale_gap_c = fair_now - mid_now_c
    if fair_move_c is not None and mid_move_c is not None and abs(fair_move_c) >= 0.5:
        repriced_frac = mid_move_c / fair_move_c

    composite_ok = composite_move_usd_val is not None and composite_move_usd_val >= min_composite_move_usd

    fair_ok = fair_move_c is not None and abs(fair_move_c) >= min_fair_move_c
    gap_ok = stale_gap_c is not None and stale_gap_c >= min_stale_gap_c
    repriced_ok = repriced_frac is not None and repriced_frac < max_repriced_frac
    stale_core_pass = bool(fair_ok and gap_ok and repriced_ok)
    stale_trigger_would_pass = bool(stale_core_pass and composite_ok)

    fail = None
    if not fair_ok:
        fail = "fair move"
    elif not gap_ok:
        fail = "stale gap"
    elif not repriced_ok:
        fail = "repriced"

    lb = int(lookback_s)
    if fair_move_c is None or mid_move_c is None or stale_gap_c is None:
        detail = "n/a"
    else:
        rp = "—" if repriced_frac is None else f"{repriced_frac * 100:.0f}%"
        detail = (
            f"fair {fair_move_c:+.1f}c over {lb}s, mid {mid_move_c:+.1f}c, "
            f"gap {stale_gap_c:+.1f}c, repriced {rp}"
        )
    if fail and not stale_core_pass:
        detail = f"{detail} · FAIL {fail}"

    return {
        "fair_now": fair_now,
        "fair_ref": fair_ref,
        "mid_now": mid_now_c,
        "mid_ref": mid_ref_c,
        "fair_move_c": fair_move_c,
        "mid_move_c": mid_move_c,
        "stale_gap_c": stale_gap_c,
        "repriced_frac": repriced_frac,
        "composite_move_usd": composite_move_usd_val,
        "composite_move_ok": composite_ok,
        "stale_core_pass": stale_core_pass,
        "stale_trigger_would_pass": stale_trigger_would_pass,
        "stale_fail": fail,
        "detail": detail,
        "lookback_s": lookback_s,
    }


def build_stale_snapshot(
    *,
    p_up: float | None,
    yes_mid: float | None,
    no_mid: float | None,
    samples: list[tuple[float, float]],
    mid_history: list[tuple[float, float, float | None]],
    now: float,
    strike: float | None,
    move_1m: float | None,
    secs_left: float | None,
    model_cfg: dict,
    params: dict,
    min_composite_move_usd: float,
    composite: float | None,
) -> dict[str, Any]:
    lookback = float(params.get("stale_lookback_s", 10.0))
    min_fair = float(params.get("min_fair_move_c", 3.0))
    min_gap = float(params.get("min_stale_gap_c", 3.0))
    max_repr = float(params.get("max_repriced_frac", 0.4))
    comp_mv = composite_move_usd(samples, now, composite, lookback)

    up = evaluate_side_stale(
        side="UP",
        p_up_now=p_up,
        yes_mid_now=yes_mid,
        no_mid_now=no_mid,
        samples=samples,
        mid_history=mid_history,
        now=now,
        strike=strike,
        move_1m=move_1m,
        secs_left=secs_left,
        model_cfg=model_cfg,
        lookback_s=lookback,
        min_fair_move_c=min_fair,
        min_stale_gap_c=min_gap,
        max_repriced_frac=max_repr,
        composite_move_usd_val=comp_mv,
        min_composite_move_usd=min_composite_move_usd,
    )
    down = evaluate_side_stale(
        side="DOWN",
        p_up_now=p_up,
        yes_mid_now=yes_mid,
        no_mid_now=no_mid,
        samples=samples,
        mid_history=mid_history,
        now=now,
        strike=strike,
        move_1m=move_1m,
        secs_left=secs_left,
        model_cfg=model_cfg,
        lookback_s=lookback,
        min_fair_move_c=min_fair,
        min_stale_gap_c=min_gap,
        max_repriced_frac=max_repr,
        composite_move_usd_val=comp_mv,
        min_composite_move_usd=min_composite_move_usd,
    )
    return {
        "UP": up,
        "DOWN": down,
        "composite_move_usd": comp_mv,
        "min_composite_move_usd": min_composite_move_usd,
        "lookback_s": lookback,
    }


def stale_gap_bucket(gap_c: float | None) -> str:
    if gap_c is None:
        return "unknown"
    if gap_c < 3:
        return "<3c"
    if gap_c < 5:
        return "3-5c"
    if gap_c < 8:
        return "5-8c"
    return "8c+"
