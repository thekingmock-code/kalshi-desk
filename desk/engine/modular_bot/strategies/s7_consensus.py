"""S7: trade only when >=2 of S1/S2/S3 agree (applied in resolver)."""
from __future__ import annotations

from desk.engine.modular_bot.types import StrategySignal


def consensus_from_core(signals: list[StrategySignal], cfg: dict) -> StrategySignal | None:
    sc = cfg.get("strategies", {}).get("s7_consensus") or {}
    if not sc.get("enabled", True):
        return None
    core_ids = {"s1_stale_quote_lag", "s2_fair_value_divergence", "s3_settlement_lock"}
    core = [s for s in signals if s.strategy_id in core_ids]
    if len(core) < int(sc.get("min_agreeing", 2)):
        return None
    sides = {s.side for s in core}
    if len(sides) != 1:
        return None
    side = next(iter(sides))
    return StrategySignal(
        strategy_id="s7_consensus",
        side=side,
        detail=f"consensus {len(core)}/{len(core_ids)} on {side}",
        meta={"contributors": [s.strategy_id for s in core]},
    )
