"""Gate evaluation: locked rules + per-strategy checks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from desk.engine import locked as L
from desk.engine.gate_utils import all_active_pass, gate_check, gate_passing_stats
from desk.engine.model import fee_dollars


def _check(label: str, ok: bool, detail: str, *, locked: bool = False, **kw) -> dict:
    return gate_check(label, ok=ok, detail=detail, locked=locked, **kw)


@dataclass
class GateContext:
    asset: str
    side: str  # UP or DOWN
    secs_left: float | None
    bid: float | None
    ask: float | None
    prob: float | None
    flow_pct: float | None
    momentum: int | None
    vol_ratio: float | None
    sigma_t: float | None
    ref: float | None
    strike: float | None
    dual_feed_ok: bool
    feed_detail: str
    p_up: float | None
    yes_mid: float | None
    no_mid: float | None
    net_edge: float | None
    composite_pct_move_3s: float | None
    kalshi_mid_move_3s: float | None
    btc_momentum: int | None
    sol_confirm_secs: float | None
    params: dict
    index_ok: bool = False
    lag: float | None = None
    momentum_30: int | None = None
    momentum_60: int | None = None
    signal_hold_secs: float | None = None
    net_edge_entry: float | None = None
    gate_edge: float | None = None
    is_weekend: bool = False
    composite: float | None = None
    index_price: float | None = None
    coinbase_age: float | None = None
    kraken_age: float | None = None
    momentum_gate_enabled: bool = True
    chop_addon_cents: float = 0.0
    weekend_bump_cents: float = 0.0
    taker_rate: float = 0.07
    g3_settlement_enabled: bool = True
    g4_cost_adjusted_enabled: bool = True
    g4_cost_pad_cents: float = 0.5


def net_edge(prob: float | None, ask: float | None, spread: float | None, fee_fn: Callable[[float], float]) -> float | None:
    if prob is None or ask is None:
        return None
    fee = fee_fn(ask)
    half = 0.0 if spread is None else spread / 2.0
    return prob - ask - fee - half


def net_edge_entry(prob: float | None, ask: float | None, fee_fn: Callable[[float], float]) -> float | None:
    if prob is None or ask is None:
        return None
    return prob - ask - fee_fn(ask)


def gate_edge_value(basis: str, edge_net: float | None, edge_entry: float | None) -> float | None:
    if basis == "entry":
        return edge_entry
    return edge_net


def _late_bonus_cents(secs_left: float | None) -> float:
    if secs_left is not None and secs_left < L.LATE_SECS:
        return L.LATE_EDGE_EXTRA * 100.0
    return 0.0


def unified_edge_gate(ctx: GateContext, *, kind: str, ignore_edge_gates: bool = False) -> dict:
    use_edge = ctx.gate_edge if ctx.gate_edge is not None else ctx.net_edge
    edge_c = None if use_edge is None else use_edge * 100.0
    late_c = _late_bonus_cents(ctx.secs_left)
    weekend_c = float(ctx.weekend_bump_cents or 0.0)
    spread = None if ctx.ask is None or ctx.bid is None else ctx.ask - ctx.bid

    if kind == "arb":
        pad = L.ARB_PAD_BASE + (L.ARB_PAD_VOL if (ctx.vol_ratio or 0) > L.ARB_VOL_HOT else 0)
        base_c = None if spread is None else (spread + pad) * 100.0
        need_c = None if base_c is None else base_c + late_c
        ok = ignore_edge_gates or (edge_c is not None and need_c is not None and edge_c >= need_c)
        detail = (
            "bypassed (ignore edge)"
            if ignore_edge_gates
            else (
                f"edge {edge_c:.1f}c need {need_c:.1f}c (base + late + chop + weekend)"
                if edge_c is not None and need_c is not None
                else "unknown"
            )
        )
        return gate_check(
            "Edge",
            ok=bool(ok),
            detail=detail,
            hardness="hard",
            value=edge_c,
            threshold=need_c,
        )

    base_c = float(ctx.params.get("net_edge_min", 0.02)) * 100.0
    need_c = base_c + late_c + weekend_c
    ok = ignore_edge_gates or (edge_c is not None and edge_c >= need_c)
    detail = (
        "bypassed (ignore edge)"
        if ignore_edge_gates
        else (
            f"edge {edge_c:.1f}c need {need_c:.1f}c (base + late + chop + weekend)"
            if edge_c is not None
            else "unknown"
        )
    )
    return gate_check(
        "Edge",
        ok=bool(ok),
        detail=detail,
        locked=True,
        hardness="hard",
        value=edge_c,
        threshold=need_c,
    )


def locked_checks(ctx: GateContext, *, ignore_edge_gates: bool = False, skip_divergence: bool = False) -> list[dict]:
    checks: list[dict] = []
    window_ok = ctx.secs_left is not None and L.ENTRY_SECS_MIN <= ctx.secs_left <= L.ENTRY_SECS_MAX
    checks.append(
        gate_check(
            L.LOCKED_LABELS[0],
            ok=window_ok,
            detail="unknown"
            if ctx.secs_left is None
            else f"{ctx.secs_left:.0f}s left (need {L.ENTRY_SECS_MIN:.0f}–{L.ENTRY_SECS_MAX:.0f})",
            locked=True,
            hardness="hard",
            value=ctx.secs_left,
            threshold=(L.ENTRY_SECS_MIN, L.ENTRY_SECS_MAX),
        )
    )
    mid = ctx.yes_mid if ctx.side == "UP" else ctx.no_mid
    div_ok = True
    div_d = "n/a"
    div = None
    if ctx.prob is not None and mid is not None:
        div = abs(ctx.prob - mid)
        div_ok = div <= L.MID_DIVERGENCE_VETO
        div_d = f"|model−mid|={div:.2f}"
    elif ctx.prob is None or mid is None:
        div_ok = False
        div_d = "missing model or mid"
    if skip_divergence:
        div_ok = True
        div_d = (div_d + " · skipped fade") if div_d else "skipped (fade)"
    checks.append(
        gate_check(
            L.LOCKED_LABELS[1],
            ok=div_ok,
            detail=div_d,
            locked=True,
            hardness="hard",
            value=div if ctx.prob is not None and mid is not None else None,
            threshold=L.MID_DIVERGENCE_VETO,
        )
    )
    checks.append(unified_edge_gate(ctx, kind="gates", ignore_edge_gates=ignore_edge_gates))
    return checks


def _trend_sigma_ok(ctx: GateContext) -> tuple[bool, str]:
    if ctx.ref is None or ctx.strike is None or not ctx.sigma_t or ctx.sigma_t <= 0:
        return False, "unknown"
    lead = ctx.ref - ctx.strike
    sigma = lead / ctx.sigma_t
    need = float(ctx.params.get("trend_sigma_min", 0.5))
    if ctx.side == "UP":
        ok = sigma >= need
        return ok, f"{sigma:.2f}σ vs {need:.2f} need"
    ok = sigma <= -need
    return ok, f"{sigma:.2f}σ vs −{need:.2f} need"


def strategy_checks(kind: str, ctx: GateContext, *, ignore_edge_gates: bool = False) -> list[dict]:
    checks: list[dict] = []
    spread = None if ctx.ask is None or ctx.bid is None else ctx.ask - ctx.bid

    if kind == "gates":
        checks.append(unified_edge_gate(ctx, kind="gates", ignore_edge_gates=ignore_edge_gates))
        t_ok, t_d = _trend_sigma_ok(ctx)
        checks.append(gate_check("Trend σ", ok=t_ok, detail=t_d, hardness="soft"))
        if ctx.momentum_gate_enabled:
            agrees = ctx.momentum is not None and ctx.momentum > 0
            checks.append(
                gate_check(
                    "Momentum agrees",
                    ok=agrees,
                    detail="flat" if not ctx.momentum else ("with" if agrees else "against"),
                    hardness="soft",
                )
            )
        else:
            checks.append(
                gate_check(
                    "Momentum agrees",
                    ok=False,
                    detail="off",
                    status="off",
                    counts=False,
                    hardness="soft",
                )
            )
        flow_need = float(ctx.params.get("flow_min", 0.58)) * 100
        flow_ok = ctx.flow_pct is not None and ctx.flow_pct >= flow_need
        checks.append(
            gate_check(
                "Taker flow",
                ok=flow_ok,
                detail="unknown" if ctx.flow_pct is None else f"{ctx.flow_pct:.0f}%",
                hardness="soft",
                value=ctx.flow_pct,
                threshold=flow_need,
            )
        )
        vmin = float(ctx.params.get("vol_min", 0.5))
        vmax = float(ctx.params.get("vol_max", 2.0))
        vol_ok = ctx.vol_ratio is not None and vmin <= ctx.vol_ratio <= vmax
        checks.append(
            gate_check(
                "Vol band",
                ok=vol_ok,
                detail="unknown" if ctx.vol_ratio is None else f"{ctx.vol_ratio:.2f}× ({vmin}–{vmax})",
                hardness="soft",
                value=ctx.vol_ratio,
                threshold=(vmin, vmax),
            )
        )
        floor = float(ctx.params.get("ask_floor", 0.35))
        cap = float(ctx.params.get("ask_cap", 0.65))
        band_ok = ctx.ask is not None and floor <= ctx.ask <= cap
        checks.append(
            gate_check(
                "Ask band",
                ok=band_ok,
                detail="unknown" if ctx.ask is None else f"{ctx.ask * 100:.0f}¢",
                hardness="hard",
                value=ctx.ask,
                threshold=(floor, cap),
            )
        )
        sm = float(ctx.params.get("spread_max", 0.03))
        sp_ok = spread is not None and spread <= sm
        checks.append(
            gate_check(
                "Spread",
                ok=sp_ok,
                detail="unknown" if spread is None else f"{spread * 100:.1f}¢",
                hardness="hard",
                value=spread,
                threshold=sm,
            )
        )
        return checks

    if kind == "arb":
        window = ctx.secs_left is not None and L.ARB_WINDOW_MIN <= ctx.secs_left <= L.ARB_WINDOW_MAX
        checks.append(
            gate_check(
                "Arb window",
                ok=window,
                detail="unknown" if ctx.secs_left is None else f"{ctx.secs_left:.0f}s",
                hardness="hard",
                value=ctx.secs_left,
                threshold=(L.ARB_WINDOW_MIN, L.ARB_WINDOW_MAX),
            )
        )
        stale = False
        stale_d = "n/a"
        if ctx.composite_pct_move_3s is not None and ctx.kalshi_mid_move_3s is not None:
            stale = ctx.composite_pct_move_3s >= L.ARB_STALE_COMPOSITE_PCT and abs(ctx.kalshi_mid_move_3s) < 1e-6
            stale_d = f"comp {ctx.composite_pct_move_3s * 100:.3f}% · mid Δ{ctx.kalshi_mid_move_3s * 100:.3f}%"
        checks.append(
            gate_check(
                "Stale quote trigger",
                ok=stale,
                detail=stale_d,
                hardness="hard",
                value=ctx.composite_pct_move_3s,
                threshold=L.ARB_STALE_COMPOSITE_PCT,
            )
        )
        floor = float(ctx.params.get("ask_floor", 0.35))
        cap = float(ctx.params.get("ask_cap", 0.65))
        band_ok = ctx.ask is not None and floor <= ctx.ask <= cap
        checks.append(
            gate_check(
                "Ask band",
                ok=band_ok,
                detail="unknown" if ctx.ask is None else f"{ctx.ask * 100:.0f}¢",
                hardness="hard",
            )
        )
        checks.append(unified_edge_gate(ctx, kind="arb", ignore_edge_gates=ignore_edge_gates))
        sm = float(ctx.params.get("spread_max", 0.03))
        checks.append(
            gate_check(
                "Spread",
                ok=spread is not None and spread <= sm,
                detail="unknown" if spread is None else "",
                hardness="hard",
            )
        )
        return checks

    if kind == "sol":
        if ctx.asset != "SOL":
            return [gate_check("SOL only", ok=False, detail=ctx.asset, hardness="hard")]
        band_ok = ctx.ask is not None and L.SOL_ASK_MIN <= ctx.ask <= L.SOL_ASK_MAX
        checks.append(gate_check("Ask band", ok=band_ok, detail="unknown" if ctx.ask is None else f"{ctx.ask * 100:.0f}¢", hardness="hard"))
        use_edge = ctx.gate_edge if ctx.gate_edge is not None else ctx.net_edge
        edge_s = "unknown" if use_edge is None else f"{use_edge * 100:+.1f}¢"
        checks.append(
            gate_check(
                "Edge",
                ok=use_edge is not None and use_edge >= L.SOL_NET_EDGE_MIN,
                detail=edge_s,
                hardness="hard",
            )
        )
        t_ok, t_d = _trend_sigma_ok(ctx)
        agrees = ctx.momentum is not None and ctx.momentum > 0
        prob_ok = ctx.prob is not None and ctx.prob >= 0.5
        checks.append(gate_check("Trend + momentum", ok=t_ok and agrees and prob_ok, detail=t_d, hardness="soft"))
        btc_ok = ctx.btc_momentum is None or (ctx.btc_momentum > 0 and agrees) or (ctx.btc_momentum < 0 and not agrees)
        checks.append(gate_check("BTC confirms", ok=btc_ok, detail="BTC mom aligned" if btc_ok else "BTC disagrees", hardness="soft"))
        chase = ctx.vol_ratio is not None and ctx.vol_ratio > 2.2 and ctx.momentum is not None and ctx.momentum != 0
        checks.append(gate_check("Spike/chase filter", ok=not chase, detail="spike" if chase else "ok", hardness="soft"))
        confirm_ok = ctx.sol_confirm_secs is not None and ctx.sol_confirm_secs >= L.SOL_CONFIRM_SECS
        checks.append(
            gate_check(
                "3s entry confirm",
                ok=confirm_ok,
                detail="unknown" if ctx.sol_confirm_secs is None else f"{ctx.sol_confirm_secs:.1f}s",
                hardness="hard",
            )
        )
        return checks

    if kind == "scanner":
        cheap = ctx.ask is not None and ctx.ask <= L.SUB25_ASK_MAX
        checks.append(gate_check("Ask ≤25¢", ok=cheap, detail="unknown" if ctx.ask is None else f"{ctx.ask * 100:.1f}¢", hardness="hard"))
        use_edge = ctx.gate_edge if ctx.gate_edge is not None else ctx.net_edge
        edge_s = "unknown" if use_edge is None else f"{use_edge * 100:+.1f}¢"
        checks.append(
            gate_check(
                "Edge",
                ok=use_edge is not None and use_edge >= L.SUB25_EDGE_MIN,
                detail=edge_s,
                hardness="hard",
            )
        )
        outside = ctx.secs_left is not None and ctx.secs_left > L.SUB25_BLACKOUT
        checks.append(gate_check("Outside last 2m", ok=outside, detail="unknown" if ctx.secs_left is None else f"{ctx.secs_left:.0f}s", hardness="hard"))
        if ctx.momentum is not None and ctx.momentum > 0:
            checks.append(gate_check("Breakout (YES only)", ok=ctx.side == "UP", detail="YES breakout lane", hardness="soft"))
        elif ctx.momentum is not None and ctx.momentum < 0:
            checks.append(gate_check("Exhaustion (NO only)", ok=ctx.side == "DOWN", detail="NO exhaustion lane", hardness="soft"))
        else:
            checks.append(gate_check("Breakout / exhaustion", ok=False, detail="flat momentum", hardness="soft"))
        checks.append(gate_check("Log only", ok=True, detail="not wired to paper", counts=False, hardness="soft"))
        return checks

    return [gate_check("Strategy", ok=False, detail=kind or "unknown", hardness="hard")]


def evaluate_side(
    *,
    strategy: dict,
    ctx_base: GateContext,
    fee_fn: Callable[[float], float],
    ignore_edge_gates: bool = False,
    skip_divergence: bool = False,
) -> list[dict]:
    del fee_fn
    kind = strategy.get("kind")
    if kind == "hour":
        return [gate_check("15m desk only", ok=False, detail="use 1h product", hardness="hard")]
    if kind == "weekend_money":
        from desk.engine.weekend_money import weekend_checks

        return weekend_checks(ctx_base, ignore_edge_gates=ignore_edge_gates)
    if kind == "arb":
        return strategy_checks("arb", ctx_base, ignore_edge_gates=ignore_edge_gates)
    locked = locked_checks(ctx_base, ignore_edge_gates=ignore_edge_gates, skip_divergence=skip_divergence)
    strat = strategy_checks(kind, ctx_base, ignore_edge_gates=ignore_edge_gates)
    if kind == "gates":
        strat = [c for c in strat if c.get("label") != "Edge"]
    return locked + strat


def all_pass(checks: list[dict]) -> bool:
    return all_active_pass(checks)


def passing_count(checks: list[dict]) -> tuple[int, int]:
    return gate_passing_stats(checks)
