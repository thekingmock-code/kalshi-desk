"""Soft gates: failure adds required edge (cents), never blocks by themselves."""
from __future__ import annotations

from desk.engine.modular_bot.context import BotContext


def soft_penalty_cents(ctx: BotContext, side: str, cfg: dict) -> tuple[float, list[str]]:
    sg = cfg.get("soft_gates") or {}
    penalty = 0.0
    notes: list[str] = []

    trend_sig = float(sg.get("trend_sigma_threshold", 2.0))
    trend_pen = float(sg.get("trend_sigma_penalty_cents", 2))
    if ctx.sigma_t and ctx.composite and ctx.strike:
        lead = abs(ctx.composite - ctx.strike)
        sig = lead / ctx.sigma_t if ctx.sigma_t > 0 else 0
        if sig >= trend_sig:
            penalty += trend_pen
            notes.append(f"trend σ {sig:.1f}")

    mom_pen = float(sg.get("momentum_penalty_cents", 1.5))
    if ctx.momentum is not None:
        against = (side == "UP" and ctx.momentum < 0) or (side == "DOWN" and ctx.momentum > 0)
        if against:
            penalty += mom_pen
            notes.append("momentum against")

    flow_pen = float(sg.get("taker_flow_penalty_cents", 1))
    if ctx.buy_pct is not None:
        if side == "UP" and ctx.buy_pct < 45:
            penalty += flow_pen
            notes.append("weak buy flow")
        if side == "DOWN" and ctx.buy_pct > 55:
            penalty += flow_pen
            notes.append("strong buy flow vs DOWN")

    vol_lo = float(sg.get("vol_ratio_min", 0.5))
    vol_hi = float(sg.get("vol_ratio_max", 2.5))
    vol_pen = float(sg.get("vol_band_penalty_cents", 2))
    if ctx.vol_ratio is not None and (ctx.vol_ratio < vol_lo or ctx.vol_ratio > vol_hi):
        penalty += vol_pen
        notes.append(f"vol ratio {ctx.vol_ratio:.2f}")

    btc_pen = float(sg.get("btc_confirm_penalty_cents", 3))
    if ctx.asset in ("SOL", "BNB") and sg.get("btc_confirm_enabled", True):
        if ctx.btc_momentum is not None:
            if side == "UP" and ctx.btc_momentum < 0:
                penalty += btc_pen
                notes.append("BTC not confirming UP")
            if side == "DOWN" and ctx.btc_momentum > 0:
                penalty += btc_pen
                notes.append("BTC not confirming DOWN")

    return penalty, notes
