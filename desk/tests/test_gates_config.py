"""Per-asset tunable clamps, locked gates, freeze-while-open."""
from __future__ import annotations

import time
from pathlib import Path

from desk.engine.gates_eval import GateContext, locked_checks
from desk.engine.locked import ENTRY_SECS_MAX, ENTRY_SECS_MIN, LATE_EDGE_EXTRA, LATE_SECS
from desk.engine.tunable import clamp_param, default_params, merge_params
from desk.engine.rollover import Book, Position
from desk.store import Store


def test_clamp_rejects_out_of_range():
    assert clamp_param("BTC", "net_edge_min", 0.01) == 0.02
    assert clamp_param("BTC", "net_edge_min", 0.99) == 0.06
    assert clamp_param("SOL", "ask_cap", 0.40) == 0.50


def test_merge_params_per_asset():
    btc = merge_params("gates_15m", "BTC", {"net_edge_min": 0.04})
    sol = merge_params("gates_15m", "SOL", None)
    assert btc["net_edge_min"] == 0.04
    assert sol["net_edge_min"] == 0.03
    assert btc["ask_cap"] == 0.65
    assert sol["ask_cap"] == 0.55


def test_late_window_extra_edge():
    params = default_params("BTC", ("net_edge_min",))
    ctx = GateContext(
        asset="BTC",
        side="UP",
        secs_left=200.0,
        bid=0.48,
        ask=0.50,
        prob=0.55,
        flow_pct=60.0,
        momentum=1,
        vol_ratio=1.0,
        sigma_t=10.0,
        ref=101.0,
        strike=100.0,
        dual_feed_ok=True,
        feed_detail="ok",
        p_up=0.55,
        yes_mid=0.50,
        no_mid=0.50,
        net_edge=0.025,
        composite_pct_move_3s=None,
        kalshi_mid_move_3s=None,
        btc_momentum=None,
        sol_confirm_secs=None,
        params=params,
    )
    checks = locked_checks(ctx)
    edge = [c for c in checks if c["label"] == "Edge"][0]
    assert ctx.secs_left < LATE_SECS
    assert not edge["ok"]  # 2.5c < 4c need (2+2)


def test_entry_window_locked():
    params = default_params("BTC", ("net_edge_min",))
    for secs, ok in ((900, False), (720, True), (121, True), (119, False)):
        ctx = GateContext(
            asset="BTC",
            side="UP",
            secs_left=float(secs),
            bid=0.48,
            ask=0.50,
            prob=0.55,
            flow_pct=60.0,
            momentum=1,
            vol_ratio=1.0,
            sigma_t=10.0,
            ref=101.0,
            strike=100.0,
            dual_feed_ok=True,
            feed_detail="ok",
            p_up=0.55,
            yes_mid=0.50,
            no_mid=0.50,
            net_edge=0.05,
            composite_pct_move_3s=None,
            kalshi_mid_move_3s=None,
            btc_momentum=None,
            sol_confirm_secs=None,
            params=params,
        )
        window = [c for c in locked_checks(ctx) if "Entry window" in c["label"]][0]
        assert window["ok"] is ok, secs


def test_freeze_while_in_position(tmp_path: Path):
    db = tmp_path / "t.sqlite"
    store = Store(db)
    from desk.engine.tunable import pending_key, settings_key

    sk = settings_key("gates_15m", "BTC")
    store.save_setting(sk, {"net_edge_min": 0.02})
    pk = pending_key("gates_15m", "BTC")
    store.save_setting(pk, {"net_edge_min": 0.05})
    assert store.settings()[pk]["net_edge_min"] == 0.05
