"""Per-rule exit modes: OFF, SHADOW, ACTIVE. Master exits_enabled still overrides."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

MODES = ("OFF", "SHADOW", "ACTIVE")


def _mode(rules: dict, key: str, default: str = "SHADOW") -> str:
    v = rules.get(key)
    if v is None:
        return default
    if isinstance(v, bool):
        return "ACTIVE" if v else "OFF"
    s = str(v).upper()
    return s if s in MODES else default


def rule_catalog(strategy: dict | None) -> list[dict[str, str]]:
    """UI + config keys for each rule."""
    p = (strategy or {}).get("params") or {}
    return [
        {"id": "entry_grace", "config_key": "entry_grace_enabled", "label": "Entry grace (modifier)"},
        {"id": "bank", "config_key": "bank_mode", "label": "Bank big win"},
        {"id": "wrong_side_exit", "config_key": "wrong_side_exit_mode", "label": "Wrong-side recover exit"},
        {"id": "hard_stop", "config_key": "hard_stop_mode", "label": "Hard stop (loss %)"},
        {"id": "reverse", "config_key": "reverse_mode", "label": "Reverse side"},
        {"id": "thin_profit", "config_key": "thin_profit_mode", "label": "Thin profit exit"},
        {"id": "trail", "config_key": "trail_mode", "label": "Trail off high"},
        {"id": "breakeven", "config_key": "breakeven_mode", "label": "Breakeven after gain"},
        {"id": "arb_escape", "config_key": "arb_escape_mode", "label": "Spot arb escape"},
        {"id": "arb_cap", "config_key": "arb_cap_mode", "label": "Spot arb hard cap"},
        {"id": "arb_reversal", "config_key": "arb_reversal_mode", "label": "Spot arb reversal guard"},
        {"id": "hour_stop", "config_key": "hour_stop_mode", "label": "Hour stop bid"},
    ]


def net_pnl_at_bid(*, entry: float | None, bid: float | None, contracts: float, entry_fee: float, exit_fee: float) -> float | None:
    if entry is None or bid is None:
        return None
    return (bid - entry) * contracts - entry_fee - exit_fee


@dataclass
class RuleEval:
    rule_id: str
    mode: str
    would_fire: bool
    blocked_by_grace: bool = False
    detail: str = ""
    exit_price: float | None = None
    net_pnl_if_exit: float | None = None

    @property
    def fires_active(self) -> bool:
        return self.mode == "ACTIVE" and self.would_fire and not self.blocked_by_grace


@dataclass
class ExitEvaluation:
    action: str
    reasons: list[str]
    active_rule: str | None = None
    next_hint: str | None = None
    rule_evals: list[RuleEval] = field(default_factory=list)
    wrong_side_confirm_since: float | None = None

    def shadow_rows(self) -> list[dict[str, Any]]:
        out = []
        for r in self.rule_evals:
            if r.mode != "SHADOW" or not r.would_fire:
                continue
            out.append(
                {
                    "rule": r.rule_id,
                    "would_have_fired": True,
                    "detail": r.detail,
                    "exit_price": r.exit_price,
                    "net_pnl_if_exit": r.net_pnl_if_exit,
                }
            )
        return out


def _in_entry_grace(ctx: Any, rules: dict) -> bool:
    if not rules.get("entry_grace_enabled", True):
        return False
    grace = float(rules.get("entry_grace_secs", 75))
    return ctx.held_for is not None and ctx.held_for < grace


def _eval_bank(ctx: Any, rules: dict, fees: dict) -> RuleEval:
    mode = _mode(rules, "bank_mode", "ACTIVE")
    bid_c = float(rules.get("bank_bid_cents", rules.get("bank_price", 0.95) * 100)) / 100.0
    min_left = float(rules.get("bank_min_secs_left", rules.get("bank_secs_left", 45)))
    bid = ctx.held_bid
    ok = (
        bid is not None
        and ctx.secs_left is not None
        and bid >= bid_c
        and ctx.secs_left > min_left
    )
    detail = f"bid {bid * 100 if bid else 0:.0f}¢ need ≥{bid_c * 100:.0f}¢ and T>{min_left:.0f}s"
    return RuleEval(
        rule_id="bank",
        mode=mode,
        would_fire=bool(ok),
        blocked_by_grace=False,
        detail=detail,
        exit_price=bid,
        net_pnl_if_exit=None,
    )


def _eval_wrong_side(ctx: Any, rules: dict, *, confirm_since: float | None, now: float) -> tuple[RuleEval, float | None]:
    mode = _mode(rules, "wrong_side_exit_mode", "ACTIVE")
    thresh = float(rules.get("wrong_side_recover_pct", rules.get("recover_prob", 0.35)))
    confirm = float(rules.get("wrong_side_confirm_secs", 3))
    cond = bool(ctx.wrong and ctx.recover_p is not None and ctx.recover_p < thresh)
    since = confirm_since
    if cond:
        if since is None:
            since = now
    else:
        since = None
    grace = _in_entry_grace(ctx, rules)
    confirmed = cond and since is not None and (now - since) >= confirm and not grace
    detail = f"wrong={ctx.wrong} recover {ctx.recover_p * 100 if ctx.recover_p is not None else '—'}% < {thresh * 100:.0f}% confirm {confirm:.0f}s"
    ev = RuleEval(
        rule_id="wrong_side_exit",
        mode=mode,
        would_fire=confirmed,
        blocked_by_grace=grace and cond,
        detail=detail,
        exit_price=ctx.held_bid,
    )
    return ev, since


def _eval_hard_stop(ctx: Any, rules: dict) -> RuleEval:
    mode = _mode(rules, "hard_stop_mode", "SHADOW")
    loss_at = float(rules.get("exit_loss_frac", 0.42))
    ok = ctx.loss_frac >= loss_at
    grace = _in_entry_grace(ctx, rules)
    return RuleEval(
        rule_id="hard_stop",
        mode=mode,
        would_fire=ok,
        blocked_by_grace=grace and ok,
        detail=f"loss {ctx.loss_frac * 100:.0f}% vs {loss_at * 100:.0f}%",
        exit_price=ctx.held_bid,
    )


def _eval_reverse(ctx: Any, rules: dict) -> RuleEval:
    mode = _mode(rules, "reverse_mode", "SHADOW")
    ok = bool(
        ctx.wrong
        and ctx.other_prob is not None
        and ctx.secs_left is not None
        and ctx.other_ask is not None
        and ctx.other_prob >= float(rules.get("reverse_prob", 0.80))
        and ctx.secs_left >= float(rules.get("reverse_secs_left", 60))
        and ctx.other_ask <= float(rules.get("reverse_price_max", 0.90))
    )
    grace = _in_entry_grace(ctx, rules)
    return RuleEval(
        rule_id="reverse",
        mode=mode,
        would_fire=ok,
        blocked_by_grace=grace and ok,
        detail="reverse signal",
        exit_price=ctx.held_bid,
    )


def _eval_thin_profit(ctx: Any, rules: dict) -> RuleEval:
    mode = _mode(rules, "thin_profit_mode", "SHADOW")
    ok = bool(
        ctx.wrong is False
        and ctx.recover_p is not None
        and ctx.pnl is not None
        and ctx.recover_p < float(rules.get("thin_prob", 0.55))
        and ctx.pnl > 0
    )
    grace = _in_entry_grace(ctx, rules)
    return RuleEval(
        rule_id="thin_profit",
        mode=mode,
        would_fire=ok,
        blocked_by_grace=grace and ok,
        detail=f"thin recover {ctx.recover_p * 100 if ctx.recover_p else 0:.0f}%",
        exit_price=ctx.held_bid,
    )


def _eval_trail_breakeven(ctx: Any, strategy: dict | None, rules: dict) -> list[RuleEval]:
    out: list[RuleEval] = []
    p = (strategy or {}).get("params") or {}
    kind = (strategy or {}).get("kind")
    bid = ctx.held_bid
    grace = _in_entry_grace(ctx, rules)
    if kind in ("gates", "weekend_money") and bid is not None and ctx.entry is not None and ctx.high_water is not None:
        trail_m = _mode(rules, "trail_mode", "SHADOW")
        trail = float(p.get("trail_retrace", 0.09))
        trail_ok = ctx.high_water > ctx.entry and bid <= ctx.high_water * (1 - trail)
        out.append(
            RuleEval(
                rule_id="trail",
                mode=trail_m,
                would_fire=trail_ok,
                blocked_by_grace=grace and trail_ok,
                detail=f"trail {trail * 100:.0f}% off high",
                exit_price=bid,
            )
        )
        be_m = _mode(rules, "breakeven_mode", "SHADOW")
        be = float(p.get("breakeven_after", 0.09))
        be_ok = ctx.high_water - ctx.entry >= be and bid <= ctx.entry
        out.append(
            RuleEval(
                rule_id="breakeven",
                mode=be_m,
                would_fire=be_ok,
                blocked_by_grace=grace and be_ok,
                detail=f"breakeven after +{be * 100:.0f}¢",
                exit_price=bid,
            )
        )
    return out


def _eval_arb(ctx: Any, strategy: dict | None, rules: dict) -> list[RuleEval]:
    out: list[RuleEval] = []
    if (strategy or {}).get("kind") != "arb":
        return out
    p = (strategy or {}).get("params") or {}
    bid = ctx.held_bid
    if bid is None:
        return out
    grace = _in_entry_grace(ctx, rules)
    cap = float(p.get("hard_cap", 0.85))
    esc = float(p.get("escape_price", 0.82))
    out.append(
        RuleEval(
            rule_id="arb_escape",
            mode=_mode(rules, "arb_escape_mode", "SHADOW"),
            would_fire=bid >= esc,
            blocked_by_grace=grace and bid >= esc,
            detail=f"escape {esc * 100:.0f}¢",
            exit_price=bid,
        )
    )
    out.append(
        RuleEval(
            rule_id="arb_cap",
            mode=_mode(rules, "arb_cap_mode", "SHADOW"),
            would_fire=bid >= cap,
            blocked_by_grace=grace and bid >= cap,
            detail=f"cap {cap * 100:.0f}¢",
            exit_price=bid,
        )
    )
    rev = bool(ctx.wrong)
    out.append(
        RuleEval(
            rule_id="arb_reversal",
            mode=_mode(rules, "arb_reversal_mode", "SHADOW"),
            would_fire=rev,
            blocked_by_grace=grace and rev,
            detail="reversal guard",
            exit_price=bid,
        )
    )
    return out


def _eval_hour_stop(ctx: Any, strategy: dict | None, rules: dict) -> RuleEval | None:
    if (strategy or {}).get("kind") != "hour":
        return None
    p = (strategy or {}).get("params") or {}
    bid = ctx.held_bid
    if bid is None:
        return None
    stop = float(p.get("stop_price", 0.40))
    ok = bid <= stop
    grace = _in_entry_grace(ctx, rules)
    return RuleEval(
        rule_id="hour_stop",
        mode=_mode(rules, "hour_stop_mode", "SHADOW"),
        would_fire=ok,
        blocked_by_grace=grace and ok,
        detail=f"bid ≤ {stop * 100:.0f}¢",
        exit_price=bid,
    )


def evaluate_exits(
    ctx: Any,
    rules: dict,
    strategy: dict | None,
    *,
    now: float,
    wrong_side_confirm_since: float | None,
    contracts: float = 1.0,
    entry_fee: float = 0.0,
    exit_fee_fn=None,
) -> ExitEvaluation:
    if not ctx.in_trade:
        return ExitEvaluation(action="WAIT", reasons=["flat"])

    if not rules.get("exits_enabled", True):
        return ExitEvaluation(action="HOLD", reasons=["Exits disabled · hold to 15m settlement"])

    evals: list[RuleEval] = []
    evals.append(_eval_bank(ctx, rules, {}))
    ws, since = _eval_wrong_side(ctx, rules, confirm_since=wrong_side_confirm_since, now=now)
    evals.append(ws)
    evals.append(_eval_hard_stop(ctx, rules))
    evals.append(_eval_reverse(ctx, rules))
    evals.append(_eval_thin_profit(ctx, rules))
    evals.extend(_eval_trail_breakeven(ctx, strategy, rules))
    evals.extend(_eval_arb(ctx, strategy, rules))
    hs = _eval_hour_stop(ctx, strategy, rules)
    if hs:
        evals.append(hs)

    bid = ctx.held_bid
    exit_fee = exit_fee_fn(bid) if (exit_fee_fn and bid is not None) else 0.0
    for e in evals:
        e.net_pnl_if_exit = net_pnl_at_bid(
            entry=ctx.entry,
            bid=e.exit_price,
            contracts=contracts,
            entry_fee=entry_fee,
            exit_fee=exit_fee,
        )

    # ACTIVE priority: bank first, then others in catalog order (excluding grace modifier)
    active_order = [
        "bank",
        "hard_stop",
        "wrong_side_exit",
        "thin_profit",
        "trail",
        "breakeven",
        "arb_escape",
        "arb_cap",
        "arb_reversal",
        "hour_stop",
    ]
    fired: RuleEval | None = None
    for rid in active_order:
        for e in evals:
            if e.rule_id == rid and e.fires_active:
                fired = e
                break
        if fired:
            break

    reverse_e = next((e for e in evals if e.rule_id == "reverse" and e.fires_active), None)
    if reverse_e:
        return ExitEvaluation(
            action="REVERSE",
            reasons=[f"Reverse · {reverse_e.detail}"],
            active_rule="reverse",
            rule_evals=evals,
            wrong_side_confirm_since=since,
        )

    if fired:
        label = {
            "bank": f"Bank at {fired.exit_price * 100:.0f}¢" if fired.exit_price else "Bank exit",
            "wrong_side_exit": "Wrong-side exit (low recover %)",
            "hard_stop": "Hard stop",
        }.get(fired.rule_id, fired.rule_id)
        return ExitEvaluation(
            action="EXIT NOW",
            reasons=[label + " · " + fired.detail],
            active_rule=fired.rule_id,
            rule_evals=evals,
            wrong_side_confirm_since=since,
        )

    next_hint = None
    if _in_entry_grace(ctx, rules):
        grace = float(rules.get("entry_grace_secs", 75))
        next_hint = f"Grace {ctx.held_for:.0f}s / {grace:.0f}s (bank may still fire)"
    else:
        for rid in ("bank", "wrong_side_exit"):
            e = next((x for x in evals if x.rule_id == rid and x.mode == "ACTIVE"), None)
            if e:
                next_hint = e.detail
                break

    return ExitEvaluation(
        action="HOLD",
        reasons=["Active exit rules armed"] if any(e.mode == "ACTIVE" for e in evals) else ["Hold to settlement baseline"],
        next_hint=next_hint,
        rule_evals=evals,
        wrong_side_confirm_since=since,
    )


def rules_ui_status(rules: dict, strategy: dict | None) -> list[dict]:
    rows = []
    grace_on = rules.get("entry_grace_enabled", True)
    rows.append({"id": "entry_grace", "status": "ACTIVE" if grace_on else "OFF", "note": f"{rules.get('entry_grace_secs', 75)}s"})
    for item in rule_catalog(strategy):
        rid = item["id"]
        if rid == "entry_grace":
            continue
        key = item["config_key"]
        default = "ACTIVE" if rid in ("bank", "wrong_side_exit") else "SHADOW"
        rows.append({"id": rid, "label": item["label"], "status": _mode(rules, key, default)})
    return rows
