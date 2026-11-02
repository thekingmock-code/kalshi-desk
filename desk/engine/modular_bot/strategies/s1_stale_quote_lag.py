"""S1: stale Kalshi quote vs composite move (sigma + repricing)."""
from __future__ import annotations

import math

from desk.engine.modular_bot.context import BotContext
from desk.engine.modular_bot.types import StrategySignal
from desk.engine.stale_quote import build_stale_snapshot, composite_move_usd


def _mid_history_yes_no(ctx: BotContext) -> list[tuple[float, float, float | None]]:
    rows: list[tuple[float, float, float | None]] = []
    for ts, yes_mid in ctx.mid_history:
        rows.append((ts, yes_mid, ctx.no_mid))
    return rows


def evaluate_s1(ctx: BotContext, cfg: dict) -> StrategySignal | None:
    sc = cfg.get("strategies", {}).get("s1_stale_quote_lag") or {}
    if not sc.get("enabled", True):
        return None
    lookback = float(sc.get("lookback_s", 10))
    sigma_mult = float(sc.get("min_move_sigma", 1.5))
    max_repr = float(sc.get("max_repriced_frac", 0.35))
    min_usd = float(sc.get("min_composite_move_usd", 5))

    if ctx.composite is None or ctx.strike is None or ctx.move_1m is None:
        return None
    comp_mv = composite_move_usd(ctx.samples, ctx.ts, ctx.composite, lookback)
    if comp_mv is None:
        return None
    sigma_usd = ctx.move_1m * math.sqrt(lookback / 60.0) if ctx.move_1m > 0 else None
    if sigma_usd is None or sigma_usd <= 0:
        return None
    if comp_mv < sigma_mult * sigma_usd:
        return None

    params = {
        "stale_lookback_s": lookback,
        "min_fair_move_c": float(sc.get("min_fair_move_c", 3)),
        "min_stale_gap_c": float(sc.get("min_stale_gap_c", 3)),
        "max_repriced_frac": max_repr,
    }
    snap = build_stale_snapshot(
        p_up=ctx.p_up,
        yes_mid=ctx.yes_mid,
        no_mid=ctx.no_mid,
        samples=ctx.samples,
        mid_history=_mid_history_yes_no(ctx),
        now=ctx.ts,
        strike=ctx.strike,
        move_1m=ctx.move_1m,
        secs_left=ctx.secs_left,
        model_cfg=ctx.model_cfg,
        params=params,
        min_composite_move_usd=min_usd,
        composite=ctx.composite,
    )
    for side in ("UP", "DOWN"):
        row = snap[side]
        if not row.get("stale_trigger_would_pass"):
            continue
        fm = row.get("fair_move_c") or 0
        if fm == 0:
            continue
        pick = "UP" if fm > 0 else "DOWN"
        return StrategySignal(
            strategy_id="s1_stale_quote_lag",
            side=pick,
            detail=row.get("detail") or "stale lag",
            meta={"snap": row, "composite_move_usd": comp_mv},
        )
    return None
