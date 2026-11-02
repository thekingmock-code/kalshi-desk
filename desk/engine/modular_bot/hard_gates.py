"""Shared hard gates for modular bot (defaults tunable in config)."""
from __future__ import annotations

from desk.engine.gates_eval import net_edge
from desk.engine.model import fee_dollars

from desk.engine.modular_bot.context import BotContext
from desk.engine.modular_bot.types import HardGateResult


def _ask_band(side: str, ctx: BotContext, ask_min: float, ask_max: float) -> tuple[bool, str]:
    ask = ctx.yes_ask if side == "UP" else ctx.no_ask
    if ask is None:
        return False, "missing ask"
    c = ask * 100.0
    if c < ask_min or c > ask_max:
        return False, f"ask {c:.0f}c outside {ask_min:.0f}-{ask_max:.0f}c"
    return True, f"ask {c:.0f}c ok"


def evaluate_hard_gates(
    ctx: BotContext,
    *,
    side: str,
    cfg: dict,
    prob: float | None,
) -> HardGateResult:
    hg = cfg.get("hard_gates") or {}
    t_min = float(hg.get("secs_left_min", 60))
    t_max = float(hg.get("secs_left_max", 810))
    ask_min = float(hg.get("ask_min_cents", 15))
    ask_max = float(hg.get("ask_max_cents", 85))
    per_asset = (hg.get("ask_band_cents") or {}).get(ctx.asset) or {}
    if per_asset:
        ask_min = float(per_asset.get("min", ask_min))
        ask_max = float(per_asset.get("max", ask_max))
    max_spread_c = float(hg.get("max_spread_cents", 12))
    min_edge_c = float(hg.get("min_net_edge_cents", 0))

    checks: list[dict] = []
    first_block: str | None = None

    def add(label: str, ok: bool, detail: str) -> None:
        nonlocal first_block
        checks.append({"label": label, "ok": ok, "detail": detail})
        if not ok and first_block is None:
            first_block = label

    if ctx.secs_left is None:
        add("Time left", False, "no market")
    else:
        ok = t_min <= ctx.secs_left <= t_max
        add("Time left", ok, f"{ctx.secs_left:.0f}s (want {t_min:.0f}-{t_max:.0f})")

    ask_ok, ask_detail = _ask_band(side, ctx, ask_min, ask_max)
    add("Ask band", ask_ok, ask_detail)

    bid = ctx.yes_bid if side == "UP" else ctx.no_bid
    ask = ctx.yes_ask if side == "UP" else ctx.no_ask
    spread_c = None
    if bid is not None and ask is not None:
        spread_c = (ask - bid) * 100.0
        add("Spread", spread_c <= max_spread_c, f"{spread_c:.1f}c (max {max_spread_c:.0f}c)")
    else:
        add("Spread", False, "missing bid/ask")

    rate = ctx.taker_rate

    def fee_fn(price: float) -> float:
        return fee_dollars(1, price, rate)

    spread = None if bid is None or ask is None else ask - bid
    edge = net_edge(prob, ask, spread, fee_fn)
    edge_c = None if edge is None else edge * 100.0
    if edge_c is None:
        add("Net edge", False, "unknown")
    else:
        add("Net edge", edge_c >= min_edge_c, f"{edge_c:.1f}c (min {min_edge_c:.1f}c)")

    if hg.get("one_entry_per_market", True) and ctx.already_entered_market:
        add("One entry / window", False, "already entered this market")
    else:
        add("One entry / window", True, "ok")

    if ctx.has_open_position and ctx.open_side and ctx.open_side != side:
        add("No opposite stack", False, f"open {ctx.open_side} vs {side}")
    else:
        add("No opposite stack", True, "ok")

    if cfg.get("kill_switch"):
        add("Kill switch", False, "kill_switch=true")
    else:
        add("Kill switch", True, "off")

    risk = cfg.get("risk") or {}
    daily_pnl = float(ctx.risk_state.get("daily_pnl", 0))
    cap = float(risk.get("daily_loss_cap_usd", 999999))
    if daily_pnl <= -cap:
        add("Daily loss cap", False, f"pnl {daily_pnl:.2f} <= -{cap:.2f}")
    else:
        add("Daily loss cap", True, "ok")

    streak = int(ctx.risk_state.get("loss_streak", 0))
    pause_at = int(risk.get("loss_streak_pause", 999))
    if streak >= pause_at:
        add("Loss streak", False, f"streak {streak} >= {pause_at}")
    else:
        add("Loss streak", True, "ok")

    ok_all = all(c["ok"] for c in checks)
    return HardGateResult(ok=ok_all, first_block=first_block, checks=checks)
