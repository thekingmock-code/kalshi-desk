"""Conflict resolver: disagree → skip; agree → one side + contributor tags."""
from __future__ import annotations

from desk.engine.modular_bot.strategies.s7_consensus import consensus_from_core
from desk.engine.modular_bot.types import StrategySignal


def resolve_signals(signals: list[StrategySignal], cfg: dict) -> tuple[str | None, list[str], str | None]:
    """
    Returns (side, contributing_strategy_ids, skip_reason).
    S5 log-only never sets trade side unless explicitly allowed.
    """
    if not signals:
        return None, [], "no strategy signals"

    trade_signals: list[StrategySignal] = []
    for s in signals:
        if s.strategy_id == "s5_cross_venue_divergence" and s.meta.get("log_only"):
            continue
        trade_signals.append(s)

    consensus = consensus_from_core(signals, cfg)
    if consensus and (cfg.get("strategies", {}).get("s7_consensus") or {}).get("require_consensus", False):
        side = consensus.side
        contrib = list({s.strategy_id for s in trade_signals if s.side == side})
        if consensus.strategy_id not in contrib:
            contrib.append(consensus.strategy_id)
        return side, contrib, None

    if not trade_signals:
        return None, [s.strategy_id for s in signals], "log-only signals only"

    sides = {s.side for s in trade_signals}
    if len(sides) > 1:
        ids = [s.strategy_id for s in trade_signals]
        return None, ids, f"conflict sides {sorted(sides)}"

    side = trade_signals[0].side
    contrib = sorted({s.strategy_id for s in trade_signals if s.side == side})
    return side, contrib, None
