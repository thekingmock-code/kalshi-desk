"""THE WEEKEND MONEY six-gate stack."""
from __future__ import annotations

from desk.engine.gates_eval import GateContext, net_edge
from desk.engine.weekend_money import (
    ENTRY_SECS_MAX,
    ENTRY_SECS_MIN,
    SAFEGUARD_SECS,
    required_prob_edge_cents,
    weekend_checks,
)


def _ctx(**kw) -> GateContext:
    base = dict(
        asset="BTC",
        side="UP",
        secs_left=400.0,
        bid=0.46,
        ask=0.48,
        prob=0.55,
        flow_pct=60.0,
        momentum=1,
        vol_ratio=1.0,
        sigma_t=10.0,
        ref=103.0,
        strike=100.0,
        dual_feed_ok=True,
        feed_detail="ok",
        p_up=0.55,
        yes_mid=0.47,
        no_mid=0.53,
        net_edge=0.03,
        composite_pct_move_3s=0.0001,
        kalshi_mid_move_3s=0.0001,
        btc_momentum=1,
        sol_confirm_secs=None,
        params={
            "trend_sigma_min": 0.30,
            "prob_edge_min_cents": 3.0,
            "ask_floor": 0.38,
            "ask_cap": 0.55,
            "spread_max": 0.03,
            "entry_hold_secs": 5.0,
        },
        index_ok=True,
        lag=0.5,
        momentum_30=1,
        momentum_60=1,
        signal_hold_secs=5.0,
    )
    base.update(kw)
    return GateContext(**base)


def test_timing_warmup_and_safeguard():
    checks = weekend_checks(_ctx(secs_left=ENTRY_SECS_MAX + 1))
    g6 = [c for c in checks if "G6" in c["label"]][0]
    assert not g6["ok"]
    checks2 = weekend_checks(_ctx(secs_left=SAFEGUARD_SECS))
    assert not [c for c in checks2 if "G6" in c["label"]][0]["ok"]
    checks3 = weekend_checks(_ctx(secs_left=ENTRY_SECS_MIN + 5))
    assert [c for c in checks3 if "G6" in c["label"]][0]["ok"]


def test_all_gates_can_pass():
    checks = weekend_checks(_ctx())
    assert all(c["ok"] for c in checks)


def test_settlement_view_blocks_wrong_side():
    up = weekend_checks(_ctx(side="UP", p_up=0.45, prob=0.45))
    g3 = [c for c in up if "G3" in c["label"]][0]
    assert not g3["ok"]


def test_dynamic_edge_tightens_late():
    early = required_prob_edge_cents(_ctx(secs_left=700))
    late = required_prob_edge_cents(_ctx(secs_left=100))
    assert late > early
