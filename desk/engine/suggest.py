"""Suggestion priority. In-trade exits via exit_rules (per-rule ACTIVE/SHADOW)."""
from __future__ import annotations

from dataclasses import dataclass

from desk.engine.exit_rules import evaluate_exits


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
    paper_enabled: bool = False
    paper_maxed: bool = False
    paper_entries_used: int = 0
    paper_entries_max: int = 2
    wrong_side_confirm_since: float | None = None
    eval_now: float = 0.0
    entry_fee: float = 0.0
    contracts: float = 1.0


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
        if ctx.paper_enabled:
            reasons.append(f"paper entries {ctx.paper_entries_used}/{ctx.paper_entries_max} this market")
            if ctx.gates_pass and not ctx.paper_maxed:
                reasons.append("paper · fill at live ask when cooldown clears")
                return "ENTER", reasons
            if ctx.paper_maxed:
                reasons.append("paper · entry cap reached for this market")
        else:
            reasons.append("observe only · no order")
        return "WAIT", reasons

    def _fee(bid: float) -> float:
        from desk.engine.model import fee_dollars

        rate = float(rules.get("_taker_rate", 0.07))
        return fee_dollars(ctx.contracts, bid, rate)

    ev = evaluate_exits(
        ctx,
        rules,
        strategy,
        now=ctx.eval_now or 0.0,
        wrong_side_confirm_since=ctx.wrong_side_confirm_since,
        contracts=ctx.contracts,
        entry_fee=ctx.entry_fee,
        exit_fee_fn=_fee,
    )
    reasons = list(ev.reasons)
    if ev.next_hint:
        reasons.append(f"Next: {ev.next_hint}")
    return ev.action, reasons
