"""S6: fade sharp Kalshi move not confirmed by composite."""
from __future__ import annotations

from desk.engine.modular_bot.context import BotContext
from desk.engine.modular_bot.types import StrategySignal


def evaluate_s6(ctx: BotContext, cfg: dict) -> StrategySignal | None:
    sc = cfg.get("strategies", {}).get("s6_fade") or {}
    if not sc.get("enabled", True):
        return None
    kalshi_move = ctx.kalshi_mid_move_3s
    comp_move = ctx.composite_pct_move_3s
    if kalshi_move is None or comp_move is None:
        return None
    min_k = float(sc.get("min_kalshi_mid_move_cents", 3))
    max_comp = float(sc.get("max_composite_confirm_pct", 0.015))
    if abs(kalshi_move * 100) < min_k:
        return None
    if abs(comp_move) > max_comp:
        return None
    side = "DOWN" if kalshi_move > 0 else "UP"
    return StrategySignal(
        strategy_id="s6_fade",
        side=side,
        detail=f"fade kalshi {kalshi_move*100:+.1f}c vs comp {comp_move*100:.2f}%",
        meta={"kalshi_move": kalshi_move, "comp_move_pct": comp_move},
    )
