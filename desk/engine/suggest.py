"""Suggestion priority. First match wins."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SuggestCtx:
    in_trade: bool
    loss_frac: float = 0.0
    held_bid: float | None = None
    secs_left: float | None = None
    held_for: float | None = None
    wrong: bool | None = None
    recover_p: float | None = None
    other_prob: float | None = None
    other_ask: float | None = None
    pnl: float | None = None
    high_water: float | None = None
    entry: float | None = None
    favored: str | None = None
    favored_edge: float | None = None
    gates_pass: bool = False
    flat_reason: str = ""


def decide(ctx: SuggestCtx, rules: dict, strategy: dict | None = None) -> tuple[str, list[str]]:
    if not ctx.in_trade:
        reasons = []
        if ctx.flat_reason:
            reasons.append(ctx.flat_reason)
        if ctx.favored:
            edge = "unknown" if ctx.favored_edge is None else f"{ctx.favored_edge * 100:+.1f}¢"
            gate = "gates pass" if ctx.gates_pass else "gates do not all pass"
            reasons.append(f"model favors {ctx.favored} · edge {edge} · {gate}")
        if strategy and strategy.get("log_only"):
            reasons.append("scanner is log only")
        reasons.append("observe only · no order")
        return "WAIT", reasons

    loss_at = float(rules["exit_loss_frac"])
    if ctx.loss_frac >= loss_at:
        return "EXIT NOW", [f"loss {ctx.loss_frac * 100:.0f}% of cost"]

    bank_px = float(rules["bank_price"])
    bank_secs = float(rules["bank_secs_left"])
    if (
        ctx.held_bid is not None
        and ctx.secs_left is not None
        and ctx.held_bid >= bank_px
        and ctx.secs_left > bank_secs
    ):
        return "EXIT NOW", [f"held bid {ctx.held_bid * 100:.0f}¢ with {ctx.secs_left:.0f}s left"]

    grace = float(rules["entry_grace_secs"])
    if ctx.held_for is not None and ctx.held_for < grace:
        return "HOLD", [f"entry grace {ctx.held_for:.0f}s of {grace:.0f}s"]

    if (
        ctx.wrong
        and ctx.other_prob is not None
        and ctx.secs_left is not None
        and ctx.other_ask is not None
        and ctx.other_prob >= float(rules["reverse_prob"])
        and ctx.secs_left >= float(rules["reverse_secs_left"])
        and ctx.other_ask <= float(rules["reverse_price_max"])
    ):
        return "REVERSE", [
            f"wrong side · other side {ctx.other_prob * 100:.0f}% at {ctx.other_ask * 100:.0f}¢"
        ]

    if ctx.wrong and ctx.recover_p is not None and ctx.recover_p < float(rules["recover_prob"]):
        return "EXIT NOW", [f"wrong side · recover chance {ctx.recover_p * 100:.0f}%"]

    if (
        ctx.wrong is False
        and ctx.recover_p is not None
        and ctx.pnl is not None
        and ctx.recover_p < float(rules["thin_prob"])
        and ctx.pnl > 0
    ):
        return "EXIT NOW", [f"right side but only {ctx.recover_p * 100:.0f}% · in profit"]

    extra = _strategy_exit(ctx, strategy)
    if extra:
        return extra

    return "HOLD", ["rules leave the position on"]


def _strategy_exit(ctx: SuggestCtx, strategy: dict | None) -> tuple[str, list[str]] | None:
    if not strategy:
        return None
    kind = strategy.get("kind")
    p = strategy.get("params") or {}
    bid = ctx.held_bid
    if kind == "gates" and bid is not None and ctx.entry is not None and ctx.high_water is not None:
        trail = float(p.get("trail_retrace", 0.09))
        if ctx.high_water > ctx.entry and bid <= ctx.high_water * (1 - trail):
            return "EXIT NOW", [f"trail gave back {trail * 100:.0f}%"]
        be = float(p.get("breakeven_after", 0.09))
        if ctx.high_water - ctx.entry >= be and bid <= ctx.entry:
            return "EXIT NOW", [f"back to entry after +{be * 100:.0f}¢"]
    if kind == "arb" and bid is not None:
        if bid >= float(p.get("hard_cap", 0.85)):
            return "EXIT NOW", [f"hard cap {float(p['hard_cap']) * 100:.0f}¢"]
        if bid >= float(p.get("escape_price", 0.82)):
            return "EXIT NOW", [f"escape at {float(p['escape_price']) * 100:.0f}¢"]
        if ctx.wrong:
            return "EXIT NOW", ["reversal guard"]
    if kind == "hour" and bid is not None and bid <= float(p.get("stop_price", 0.40)):
        return "EXIT NOW", [f"hour stop {float(p['stop_price']) * 100:.0f}¢"]
    return None
