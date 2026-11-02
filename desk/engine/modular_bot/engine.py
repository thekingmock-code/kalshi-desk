"""Modular bot tick evaluation (dry-run by default)."""
from __future__ import annotations

import time
from typing import Any

from desk.engine.model import fair_up

from desk.engine.modular_bot.context import BotContext
from desk.engine.modular_bot.hard_gates import evaluate_hard_gates
from desk.engine.modular_bot.resolver import resolve_signals
from desk.engine.modular_bot.soft_gates import soft_penalty_cents
from desk.engine.modular_bot.strategies import EVALUATORS
from desk.engine.modular_bot.types import BotDecision, HardGateResult, StrategySignal


def default_modular_bot_cfg() -> dict:
    return {
        "enabled": True,
        "dry_run": True,
        "kill_switch": False,
        "hard_gates": {
            "secs_left_min": 60,
            "secs_left_max": 810,
            "ask_min_cents": 15,
            "ask_max_cents": 85,
            "max_spread_cents": 12,
            "min_net_edge_cents": -50,
            "one_entry_per_market": True,
        },
        "risk": {
            "max_stake_usd": 20,
            "daily_loss_cap_usd": 200,
            "loss_streak_pause": 8,
        },
        "soft_gates": {},
        "strategies": {
            "s7_consensus": {"enabled": True, "require_consensus": False, "min_agreeing": 2},
        },
    }


def merge_bot_cfg(cfg: dict | None) -> dict:
    base = default_modular_bot_cfg()
    if not cfg:
        return base
    out = {**base, **cfg}
    out["hard_gates"] = {**base["hard_gates"], **(cfg.get("hard_gates") or {})}
    out["risk"] = {**base["risk"], **(cfg.get("risk") or {})}
    out["soft_gates"] = {**base["soft_gates"], **(cfg.get("soft_gates") or {})}
    strat = dict(base.get("strategies") or {})
    strat.update(cfg.get("strategies") or {})
    out["strategies"] = strat
    return out


def _avg_60(samples: list[tuple[float, float]], now: float) -> float | None:
    window = [px for ts, px in samples if now - ts <= 60]
    if len(window) < 3:
        return None
    return sum(window) / len(window)


def evaluate_tick(ctx: BotContext, bot_cfg: dict) -> BotDecision:
    t0 = time.perf_counter()
    cfg = merge_bot_cfg(bot_cfg)
    signals: list[StrategySignal] = []
    for fn in EVALUATORS:
        sig = fn(ctx, cfg)
        if sig:
            signals.append(sig)

    side, contrib, skip = resolve_signals(signals, cfg)
    fired = [s.strategy_id for s in signals]

    if side is None:
        hard = HardGateResult(ok=False, first_block=skip or "no side", checks=[])
    else:
        prob = ctx.p_up if side == "UP" else (None if ctx.p_up is None else 1.0 - ctx.p_up)
        hard = evaluate_hard_gates(ctx, side=side, cfg=cfg, prob=prob)

    soft_pen, soft_notes = (0.0, [])
    if side:
        soft_pen, soft_notes = soft_penalty_cents(ctx, side, cfg)
        min_edge = float((cfg.get("hard_gates") or {}).get("min_net_edge_cents", 0))
        effective_min = min_edge + soft_pen
    dry = bool(cfg.get("dry_run", True))
    would = bool(side and hard.ok and not skip)
    if side and hard.ok:
        hg = cfg.get("hard_gates") or {}
        min_edge = float(hg.get("min_net_edge_cents", 0)) + soft_pen
        from desk.engine.gates_eval import net_edge
        from desk.engine.model import fee_dollars

        bid = ctx.yes_bid if side == "UP" else ctx.no_bid
        ask = ctx.yes_ask if side == "UP" else ctx.no_ask
        spread = None if bid is None or ask is None else ask - bid
        edge = net_edge(prob, ask, spread, lambda p: fee_dollars(1, p, ctx.taker_rate))
        edge_c = None if edge is None else edge * 100.0
        if edge_c is not None and edge_c < min_edge:
            would = False
            skip = skip or f"soft-adjusted edge {edge_c:.1f}c < {min_edge:.1f}c"

    t1 = time.perf_counter()
    return BotDecision(
        ts=ctx.ts,
        asset=ctx.asset,
        ticker=ctx.ticker,
        secs_left=ctx.secs_left,
        composite=ctx.composite,
        composite_avg_60s=ctx.composite_avg_60s or _avg_60(ctx.samples, ctx.ts),
        fair_up=ctx.p_up,
        yes_bid=ctx.yes_bid,
        yes_ask=ctx.yes_ask,
        no_bid=ctx.no_bid,
        no_ask=ctx.no_ask,
        depth_hint=None,
        quote_age_s=ctx.risk_state.get("quote_age_s"),
        strategies_fired=fired,
        proposed_side=side,
        contributing=contrib,
        hard_gate_ok=hard.ok,
        first_blocking_gate=hard.first_block if not hard.ok else None,
        soft_penalty_cents=soft_pen,
        would_trade=would and not dry,
        dry_run=dry,
        skip_reason=skip if not would else (("dry_run" if dry and would else None)),
        latency_ms={"evaluate_ms": (t1 - t0) * 1000},
        venue_ages=dict(ctx.feed_ages),
        extra={"soft_notes": soft_notes, "signals": [s.strategy_id + ":" + s.side for s in signals]},
    )


def enrich_fair(ctx: BotContext) -> BotContext:
    if ctx.p_up is not None:
        return ctx
    if ctx.composite is None or ctx.strike is None or ctx.secs_left is None or ctx.move_1m is None:
        return ctx
    p_up, sigma, _ = fair_up(ctx.composite, ctx.strike, ctx.move_1m, ctx.secs_left, ctx.model_cfg)
    ctx.p_up = p_up
    ctx.sigma_t = sigma
    return ctx
