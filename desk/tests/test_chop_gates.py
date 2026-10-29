from desk.engine.chop_gates import DEFAULTS, evaluate_chop_gates, integrity_block, load_chop_gates


def test_integrity_coinbase_stale():
    prefs = load_chop_gates({})
    reason = integrity_block(
        prefs=prefs,
        feed_ages={"coinbase": 3.0, "kraken": 0.5},
        quote_age_s=1.0,
        chop_partial=False,
        missing_rows=0,
    )
    assert reason == "integrity:coinbase_stale"


def test_integrity_off_skips():
    prefs = load_chop_gates({"chop_gates": {"layer0_enabled": False}})
    reason = integrity_block(
        prefs=prefs,
        feed_ages={"coinbase": 99, "kraken": 99},
        quote_age_s=99,
        chop_partial=True,
        missing_rows=9,
    )
    assert reason is None


def test_hard_block():
    prefs = {**DEFAULTS, "hard_enabled": True, "chop_hard_min": 40.0}
    view = {
        "bot": {"edge_up": 0.05, "edge_down": 0.01, "p_up": 0.6},
        "market": {"yes_ask": 0.45, "no_ask": 0.55, "yes_mid": 0.5, "no_mid": 0.5},
        "trade": {"secs_left": 600},
        "tunable_params": {"net_edge_min": 0.02},
        "_paper_modes": {"edge_basis": "net"},
        "_weekend_bump_cents": 0,
        "_asset": "BTC",
    }
    strat = {"id": "gates_15m", "kind": "gates", "params": {"net_edge_min": 0.02}}
    out = evaluate_chop_gates(
        prefs=prefs,
        would_have_entered=True,
        chop_score=25,
        chop_partial=False,
        missing_rows=0,
        feed_ages={"coinbase": 0.1, "kraken": 0.1},
        quote_age_s=0.5,
        strategy=strat,
        side="UP",
        view=view,
        is_weekend=False,
    )
    assert out.gate_layer_result == "hard_block"
    assert out.allow_entry is False
    assert out.would_have_entered is True


def test_soft_addon_blocks_low_chop():
    prefs = {**DEFAULTS, "soft_enabled": True, "layer0_enabled": False}
    view = {
        "bot": {"edge_up": 0.025, "edge_down": 0.01, "p_up": 0.55},
        "market": {"yes_ask": 0.48, "no_ask": 0.52, "yes_mid": 0.5, "no_mid": 0.5},
        "trade": {"secs_left": 600},
        "tunable_params": {"net_edge_min": 0.02},
        "_paper_modes": {"edge_basis": "net"},
        "_weekend_bump_cents": 0,
        "_asset": "BTC",
    }
    strat = {"id": "gates_15m", "kind": "gates", "params": {"net_edge_min": 0.02}}
    out = evaluate_chop_gates(
        prefs=prefs,
        would_have_entered=True,
        chop_score=20,
        chop_partial=False,
        missing_rows=0,
        feed_ages={"coinbase": 0.1, "kraken": 0.1},
        quote_age_s=0.5,
        strategy=strat,
        side="UP",
        view=view,
        is_weekend=False,
    )
    assert out.chop_addon_cents == 2.0
    assert out.gate_layer_result == "soft_raised"
    assert out.allow_entry is False


def test_all_off_still_passes_with_would_have_entered():
    prefs = load_chop_gates({"chop_gates": {"layer0_enabled": False, "soft_enabled": False, "hard_enabled": False}})
    view = {
        "bot": {"edge_up": 0.05, "edge_down": 0.01, "p_up": 0.6},
        "market": {"yes_ask": 0.45, "no_ask": 0.55},
        "trade": {"secs_left": 600},
        "tunable_params": {"net_edge_min": 0.02},
        "_paper_modes": {"edge_basis": "net"},
        "_weekend_bump_cents": 0,
        "_asset": "BTC",
    }
    strat = {"id": "gates_15m", "kind": "gates", "params": {"net_edge_min": 0.02}}
    out = evaluate_chop_gates(
        prefs=prefs,
        would_have_entered=True,
        chop_score=80,
        chop_partial=False,
        missing_rows=0,
        feed_ages={"coinbase": 0.1, "kraken": 0.1},
        quote_age_s=0.5,
        strategy=strat,
        side="UP",
        view=view,
        is_weekend=False,
    )
    assert out.allow_entry is True
    assert out.would_have_entered is True
    assert out.gate_layer_result == "passed"
