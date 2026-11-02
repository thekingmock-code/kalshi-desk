"""S4: YES ask + NO ask + fees < $1."""
from __future__ import annotations

from desk.engine.model import fee_dollars

from desk.engine.modular_bot.context import BotContext
from desk.engine.modular_bot.types import StrategySignal


def evaluate_s4(ctx: BotContext, cfg: dict) -> StrategySignal | None:
    sc = cfg.get("strategies", {}).get("s4_cross_side_arb") or {}
    if not sc.get("enabled", True):
        return None
    ya, na = ctx.yes_ask, ctx.no_ask
    if ya is None or na is None:
        return None
    rate = ctx.taker_rate
    fee = fee_dollars(1, ya, rate) + fee_dollars(1, na, rate)
    total = ya + na + fee
    buffer = float(sc.get("min_edge_dollars", 0.002))
    if total >= 1.0 - buffer:
        return None
    edge = 1.0 - total
    side = "UP" if ya <= na else "DOWN"
    return StrategySignal(
        strategy_id="s4_cross_side_arb",
        side=side,
        detail=f"bundle cost {total:.4f} edge {edge:.4f}",
        meta={"total_cost": total, "edge_dollars": edge},
    )
