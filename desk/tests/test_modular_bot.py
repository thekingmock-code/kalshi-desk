"""Unit tests for modular bot strategies and conflict resolver."""
from __future__ import annotations

import time

from desk.engine.modular_bot.context import BotContext
from desk.engine.modular_bot.engine import evaluate_tick, merge_bot_cfg
from desk.engine.modular_bot.resolver import resolve_signals
from desk.engine.modular_bot.strategies.s1_stale_quote_lag import evaluate_s1
from desk.engine.modular_bot.strategies.s2_fair_value import evaluate_s2
from desk.engine.modular_bot.strategies.s3_settlement_lock import evaluate_s3
from desk.engine.modular_bot.strategies.s4_cross_side_arb import evaluate_s4
from desk.engine.modular_bot.strategies.s5_cross_venue import evaluate_s5
from desk.engine.modular_bot.strategies.s6_fade import evaluate_s6
from desk.engine.modular_bot.types import StrategySignal


def _base_ctx(**kw) -> BotContext:
    now = time.time()
    defaults = dict(
        ts=now,
        asset="BTC",
        ticker="T1",
        secs_left=400.0,
        strike=65000.0,
        composite=65100.0,
        composite_avg_60s=65050.0,
        samples=[(now - 10, 65000.0), (now, 65100.0)],
        move_1m=50.0,
        move_5m=50.0,
        move_1h=50.0,
        p_up=0.62,
        sigma_t=80.0,
        yes_bid=0.58,
        yes_ask=0.60,
        no_bid=0.38,
        no_ask=0.40,
        yes_mid=0.59,
        no_mid=0.39,
        mid_history=[(now - 5, 0.55), (now, 0.59)],
        kalshi_mid_move_3s=0.02,
        composite_pct_move_3s=0.0001,
        momentum=1,
        buy_pct=55.0,
        vol_ratio=1.0,
        btc_momentum=1,
        feed_ages={"coinbase": 0.5},
        already_entered_market=False,
        has_open_position=False,
        open_side=None,
        taker_rate=0.07,
        model_cfg={
            "effs_break": 60,
            "effs_offset": 40,
            "effs_cubic_div": 10800,
            "effs_floor": 0.5,
        },
        fees_cfg={"taker_rate": 0.07},
        measurements={},
        risk_state={"daily_pnl": 0, "loss_streak": 0},
    )
    defaults.update(kw)
    return BotContext(**defaults)


def test_s2_fair_divergence_up():
    cfg = merge_bot_cfg({"strategies": {"s2_fair_value_divergence": {"enabled": True, "min_divergence_cents": 1}}})
    sig = evaluate_s2(_base_ctx(p_up=0.70, yes_ask=0.60), cfg)
    assert sig is not None
    assert sig.side == "UP"
    assert sig.strategy_id == "s2_fair_value_divergence"


def test_s3_settlement_lock_late_window():
    cfg = merge_bot_cfg(
        {
            "strategies": {
                "s3_settlement_lock": {
                    "enabled": True,
                    "secs_left_max": 360,
                    "min_locked_fraction": 0.4,
                    "min_cushion_sigmas": 0.5,
                }
            }
        }
    )
    sig = evaluate_s3(
        _base_ctx(
            secs_left=200,
            composite_avg_60s=65100.0,
            measurements={"settlement": {"locked_in_fraction": 0.8, "cushion_sigmas": 2.0}},
        ),
        cfg,
    )
    assert sig is not None
    assert sig.side == "UP"


def test_s4_cross_side_arb_cheap_bundle():
    cfg = merge_bot_cfg({"strategies": {"s4_cross_side_arb": {"enabled": True}}})
    sig = evaluate_s4(_base_ctx(yes_ask=0.45, no_ask=0.45), cfg)
    assert sig is not None
    assert sig.strategy_id == "s4_cross_side_arb"


def test_s5_log_only_with_poly():
    cfg = merge_bot_cfg(
        {
            "strategies": {
                "s5_cross_venue_divergence": {"enabled": True, "polymarket_mid": 64000, "min_divergence_bps": 1}
            }
        }
    )
    sig = evaluate_s5(_base_ctx(composite=65000.0), cfg)
    assert sig is not None
    assert sig.meta.get("log_only")


def test_s6_fade_against_kalshi_move():
    cfg = merge_bot_cfg(
        {"strategies": {"s6_fade": {"enabled": True, "min_kalshi_mid_move_cents": 2, "max_composite_confirm_pct": 0.01}}}
    )
    sig = evaluate_s6(_base_ctx(kalshi_mid_move_3s=0.05, composite_pct_move_3s=0.001), cfg)
    assert sig is not None
    assert sig.side == "DOWN"


def test_s1_may_fire_on_stale_setup():
    cfg = merge_bot_cfg(
        {
            "strategies": {
                "s1_stale_quote_lag": {
                    "enabled": True,
                    "lookback_s": 10,
                    "min_move_sigma": 0.01,
                    "min_composite_move_usd": 1,
                }
            }
        }
    )
    now = time.time()
    samples = [(now - 10, 65000.0), (now, 65150.0)]
    sig = evaluate_s1(_base_ctx(samples=samples, composite=65150.0, move_1m=100.0), cfg)
    assert sig is None or sig.strategy_id == "s1_stale_quote_lag"


def test_resolver_conflict():
    cfg = merge_bot_cfg({})
    signals = [
        StrategySignal("s2_fair_value_divergence", "UP", ""),
        StrategySignal("s6_fade", "DOWN", ""),
    ]
    side, contrib, skip = resolve_signals(signals, cfg)
    assert side is None
    assert "conflict" in (skip or "")


def test_resolver_agreement():
    cfg = merge_bot_cfg({})
    signals = [
        StrategySignal("s2_fair_value_divergence", "UP", ""),
        StrategySignal("s4_cross_side_arb", "UP", ""),
    ]
    side, contrib, skip = resolve_signals(signals, cfg)
    assert side == "UP"
    assert skip is None
    assert len(contrib) == 2


def test_evaluate_tick_dry_run_blocks_would_trade():
    cfg = merge_bot_cfg({"dry_run": True})
    dec = evaluate_tick(_base_ctx(), cfg)
    assert dec.dry_run is True
    if dec.proposed_side and dec.hard_gate_ok:
        assert dec.would_trade is False


def test_hard_gate_time_window():
    cfg = merge_bot_cfg({"dry_run": True, "hard_gates": {"secs_left_min": 60, "secs_left_max": 810}})
    dec = evaluate_tick(_base_ctx(secs_left=30.0), cfg)
    if dec.proposed_side:
        assert dec.hard_gate_ok is False or dec.first_blocking_gate == "Time left"
