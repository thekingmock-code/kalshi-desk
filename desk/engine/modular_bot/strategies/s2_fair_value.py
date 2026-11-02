"""S2: fair vs ask divergence (Black-Scholes d2 style fair from desk model)."""
from __future__ import annotations

from desk.engine.modular_bot.context import BotContext
from desk.engine.modular_bot.types import StrategySignal


def evaluate_s2(ctx: BotContext, cfg: dict) -> StrategySignal | None:
    sc = cfg.get("strategies", {}).get("s2_fair_value_divergence") or {}
    if not sc.get("enabled", True):
        return None
    thresh_c = float(sc.get("min_divergence_cents", 4))
    ref = ctx.composite_avg_60s if sc.get("use_60s_avg", True) else ctx.composite
    if ref is None or ctx.p_up is None:
        return None
    for side, prob, ask in (
        ("UP", ctx.p_up, ctx.yes_ask),
        ("DOWN", 1.0 - ctx.p_up, ctx.no_ask),
    ):
        if ask is None:
            continue
        div_c = (prob - ask) * 100.0
        if div_c >= thresh_c:
            return StrategySignal(
                strategy_id="s2_fair_value_divergence",
                side=side,
                detail=f"fair-ask {div_c:+.1f}c",
                meta={"divergence_c": div_c, "ref": ref},
            )
    return None
