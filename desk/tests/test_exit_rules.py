"""Exit rule modes: ACTIVE vs SHADOW vs grace."""
from __future__ import annotations

import time

from desk.engine.exit_rules import evaluate_exits
from desk.engine.load import load_config
from desk.engine.suggest import SuggestCtx, decide

CFG = load_config()


def _ctx(**kw) -> SuggestCtx:
    base = dict(
        in_trade=True,
        loss_frac=0.0,
        held_bid=0.50,
        secs_left=400.0,
        held_for=10.0,
        wrong=True,
        recover_p=0.20,
        other_prob=0.8,
        other_ask=0.45,
        pnl=-1.0,
        high_water=0.55,
        entry=0.48,
        eval_now=1000.0,
        contracts=1.0,
        entry_fee=0.01,
    )
    base.update(kw)
    return SuggestCtx(**base)


def _rules(**kw):
    r = {**CFG["suggest"], "_taker_rate": 0.07}
    r.update(kw)
    return r


def test_grace_blocks_wrong_side_not_bank():
    rules = _rules(exits_enabled=True, entry_grace_secs=75, entry_grace_enabled=True)
    ctx = _ctx(held_for=10.0, held_bid=0.96, secs_left=60, wrong=True, recover_p=0.1)
    ev = evaluate_exits(ctx, rules, CFG["strategies"]["gates_15m"], now=1000.0, wrong_side_confirm_since=990.0)
    bank = next(e for e in ev.rule_evals if e.rule_id == "bank")
    wrong = next(e for e in ev.rule_evals if e.rule_id == "wrong_side_exit")
    assert bank.fires_active
    assert ev.action == "EXIT NOW"
    assert not wrong.fires_active


def test_wrong_side_needs_confirm_window():
    rules = _rules(exits_enabled=True, wrong_side_confirm_secs=3)
    ctx = _ctx(held_for=200.0, wrong=True, recover_p=0.10)
    ev1 = evaluate_exits(ctx, rules, None, now=1000.0, wrong_side_confirm_since=None)
    assert ev1.action == "HOLD"
    ev2 = evaluate_exits(ctx, rules, None, now=1001.5, wrong_side_confirm_since=999.0)
    assert ev2.action == "HOLD"
    ev3 = evaluate_exits(ctx, rules, None, now=1003.0, wrong_side_confirm_since=999.0)
    assert ev3.action == "EXIT NOW"
    assert ev3.active_rule == "wrong_side_exit"


def test_bank_not_with_45s_or_less_left():
    rules = _rules(exits_enabled=True)
    ctx = _ctx(held_bid=0.96, secs_left=45, held_for=200.0)
    ev = evaluate_exits(ctx, rules, None, now=1000.0, wrong_side_confirm_since=None)
    bank = next(e for e in ev.rule_evals if e.rule_id == "bank")
    assert not bank.would_fire
    assert ev.action == "HOLD"


def test_shadow_hard_stop_does_not_exit():
    rules = _rules(exits_enabled=True, hard_stop_mode="SHADOW", exit_loss_frac=0.42)
    action, _ = decide(_ctx(loss_frac=0.50, held_for=200.0), rules, None)
    assert action == "HOLD"


def test_master_exits_disabled_holds():
    rules = _rules(exits_enabled=False)
    ctx = _ctx(held_bid=0.96, secs_left=120.0, held_for=200.0)
    ev = evaluate_exits(ctx, rules, None, now=1000.0, wrong_side_confirm_since=None)
    assert ev.action == "HOLD"
    assert "settlement" in ev.reasons[0].lower()


def test_active_hard_stop_exits_when_mode_active():
    rules = _rules(exits_enabled=True, hard_stop_mode="ACTIVE", exit_loss_frac=0.42)
    action, _ = decide(_ctx(loss_frac=0.50, held_for=200.0), rules, None)
    assert action == "EXIT NOW"
