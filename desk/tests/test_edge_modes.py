"""Paper edge modes for 15m Gates."""
from __future__ import annotations

from desk.engine.edge_modes import (
    fade_triggered,
    load_paper_modes,
    paper_edge_floor_ok,
    paper_gates_pass,
    pick_entry_side,
    resolve_gate_mode,
)
from desk.engine.gates_eval import net_edge, net_edge_entry


def test_net_edge_entry_no_half_spread():
    fee = lambda p: 0.01
    assert net_edge(0.5, 0.45, 0.04, fee) == 0.5 - 0.45 - 0.01 - 0.02
    assert net_edge_entry(0.5, 0.45, fee) == 0.5 - 0.45 - 0.01


def test_fade_picks_lower_edge_side():
    modes = load_paper_modes({"gates_15m_paper": {"fade_model": True, "fade_trigger_cents": 10}})
    side, mode = pick_entry_side(
        edge_up=0.03,
        edge_down=-0.01,
        modes=modes,
        p_up=0.62,
        yes_mid=0.50,
    )
    assert mode == "fade"
    assert side == "DOWN"


def test_fade_not_triggered_without_divergence():
    modes = load_paper_modes({"gates_15m_paper": {"fade_model": True}})
    side, _ = pick_entry_side(edge_up=0.03, edge_down=-0.01, modes=modes, p_up=0.52, yes_mid=0.50)
    assert side is None


def test_ignore_edge_bypasses_net_edge_check():
    modes = load_paper_modes({"gates_15m_paper": {"ignore_edge_gate": True}})
    checks = [
        {"label": "Edge", "ok": False, "locked": True},
        {"label": "Ask band", "ok": True, "status": "pass", "counts": True},
    ]
    assert paper_gates_pass(checks, modes=modes, strategy_kind="gates")


def test_min_net_edge_floor():
    modes = load_paper_modes({"gates_15m_paper": {"min_net_edge_cents": -5}})
    assert resolve_gate_mode(modes) == "floor_neg"
    assert paper_edge_floor_ok(-0.03, modes)
    assert not paper_edge_floor_ok(-0.06, modes)
