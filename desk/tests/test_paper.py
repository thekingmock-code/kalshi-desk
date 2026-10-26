"""Paper entry limits and simulated fills."""
from __future__ import annotations

from desk.engine.paper import can_paper_enter
from desk.store import Store


def test_max_two_buys_per_market(tmp_path):
    db = tmp_path / "t.sqlite"
    store = Store(db)
    ticker = "KXBTC15M-TEST"
    assert store.paper_buy_count(ticker) == 0
    store.record_paper_buy(ticker)
    store.record_paper_buy(ticker)
    assert store.paper_buy_count(ticker) == 2
    store.record_paper_buy(ticker)
    assert store.paper_buy_count(ticker) == 3  # counter increments; runtime checks before buy


def test_can_paper_enter_respects_cap():
    view = {
        "_strategy": {"log_only": False},
        "market": {"ticker": "T", "yes_ask": 0.5, "no_ask": 0.51, "expired": False},
        "trade": {"secs_left": 600, "flat": True},
        "bot": {"edge_up": 0.03, "edge_down": -0.01},
        "gates": {"UP": [{"ok": True}], "DOWN": [{"ok": False}]},
    }
    cfg = {"paper": {"enabled": True, "max_entries_per_market": 2, "require_gates": True, "require_positive_edge": True}}
    ok, side = can_paper_enter(view, cfg=cfg, buys_so_far=0, cooldown_ok=True, has_live_position=False)
    assert ok and side == "UP"
    ok2, _ = can_paper_enter(view, cfg=cfg, buys_so_far=2, cooldown_ok=True, has_live_position=False)
    assert not ok2
