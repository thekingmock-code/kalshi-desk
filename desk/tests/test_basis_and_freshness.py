from desk.engine.gates_eval import GateContext, basis_gap_check, evaluate_side
from desk.engine.weekend_money import feed_freshness_check


def _ctx(**kw) -> GateContext:
    base = dict(
        asset="BTC",
        side="UP",
        secs_left=400.0,
        bid=0.48,
        ask=0.50,
        prob=0.55,
        flow_pct=60.0,
        momentum=1,
        vol_ratio=1.0,
        sigma_t=100.0,
        ref=100.0,
        strike=99.0,
        dual_feed_ok=True,
        feed_detail="ok",
        p_up=0.55,
        yes_mid=0.50,
        no_mid=0.50,
        net_edge=0.03,
        composite_pct_move_3s=0.0,
        kalshi_mid_move_3s=0.0,
        btc_momentum=1,
        sol_confirm_secs=5.0,
        params={"basis_max_usd": 3.0},
        index_ok=True,
    )
    base.update(kw)
    return GateContext(**base)


def test_basis_blocks_when_gap_too_wide():
    c = _ctx(composite=100.0, index_price=110.0)
    chk = basis_gap_check(c)
    assert not chk["ok"]
    assert "10.00" in chk["detail"]


def test_basis_passes_when_index_missing():
    c = _ctx(index_ok=False, index_price=None, composite=100.0)
    assert basis_gap_check(c)["ok"]


def test_feed_freshness_requires_both_feeds():
    c = _ctx(
        feed_freshness_enabled=True,
        feed_max_age_secs=2.0,
        coinbase_age=1.0,
        kraken_age=2.5,
    )
    assert not feed_freshness_check(c)["ok"]
    c2 = _ctx(
        feed_freshness_enabled=True,
        feed_max_age_secs=2.0,
        coinbase_age=1.0,
        kraken_age=1.5,
    )
    assert feed_freshness_check(c2)["ok"]


def test_momentum_gate_off_passes_against():
    strategy = {"id": "gates_15m", "kind": "gates", "params": {}}
    ctx = _ctx(momentum=-1, momentum_gate_enabled=False)
    checks = evaluate_side(strategy=strategy, ctx_base=ctx, fee_fn=lambda p: 0.01)
    mom = next(c for c in checks if c["label"] == "Momentum agrees")
    assert mom["ok"] and "off" in mom["detail"]
