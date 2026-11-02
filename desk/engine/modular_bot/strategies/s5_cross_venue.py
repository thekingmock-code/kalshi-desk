"""S5: cross-venue divergence — log-only until Polymarket feed exists."""
from __future__ import annotations

from desk.engine.modular_bot.context import BotContext
from desk.engine.modular_bot.types import StrategySignal


def evaluate_s5(ctx: BotContext, cfg: dict) -> StrategySignal | None:
    sc = cfg.get("strategies", {}).get("s5_cross_venue_divergence") or {}
    if not sc.get("enabled", False):
        return None
    poly = sc.get("polymarket_mid")
    if poly is None or ctx.composite is None:
        return None
    thresh_bps = float(sc.get("min_divergence_bps", 15))
    div_bps = abs(ctx.composite - float(poly)) / ctx.composite * 10000
    if div_bps < thresh_bps:
        return None
    side = "UP" if ctx.composite > float(poly) else "DOWN"
    sig = StrategySignal(
        strategy_id="s5_cross_venue_divergence",
        side=side,
        detail=f"log-only poly div {div_bps:.1f}bps",
        meta={"log_only": True, "div_bps": div_bps},
    )
    return sig
