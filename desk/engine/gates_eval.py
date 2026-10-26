"""Gate evaluation: locked rules + per-strategy checks."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from desk.engine import locked as L


def _check(label: str, ok: bool, detail: str, *, locked: bool = False) -> dict:
    return {"label": label, "ok": bool(ok), "detail": detail, "locked": locked}


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


def net_edge(prob: float | None, ask: float | None, spread: float | None, fee_fn: Callable[[float], float]) -> float | None:
    if prob is None or ask is None:
        return None
    fee = fee_fn(ask)
    half = 0.0 if spread is None else spread / 2.0
    return prob - ask - fee - half


def locked_checks(ctx: GateContext) -> list[dict]:
    checks: list[dict] = []
    window_ok = (
        ctx.secs_left is not None and L.ENTRY_SECS_MIN <= ctx.secs_left <= L.ENTRY_SECS_MAX
    )
    checks.append(
        _check(
            L.LOCKED_LABELS[0],
            window_ok,
            "unknown"
            if ctx.secs_left is None
            else f"{ctx.secs_left:.0f}s left (need {L.ENTRY_SECS_MIN:.0f}–{L.ENTRY_SECS_MAX:.0f})",
            locked=True,
        )
    )
    checks.append(
        _check(
            L.LOCKED_LABELS[1],
            ctx.dual_feed_ok,
            ctx.feed_detail,
            locked=True,
        )
    )
    mid = ctx.yes_mid if ctx.side == "UP" else ctx.no_mid
    div_ok = True
    div_d = "n/a"
    if ctx.prob is not None and mid is not None:
        div = abs(ctx.prob - mid)
        div_ok = div <= L.MID_DIVERGENCE_VETO
        div_d = f"|model−mid|={div:.2f}"
    elif ctx.prob is None or mid is None:
        div_ok = False
        div_d = "missing model or mid"
    checks.append(_check(L.LOCKED_LABELS[2], div_ok, div_d, locked=True))
    need_extra = ctx.secs_left is not None and ctx.secs_left < L.LATE_SECS
    edge_need = ctx.params.get("net_edge_min", 0.02)
    if need_extra:
        edge_need = float(edge_need) + L.LATE_EDGE_EXTRA
    late_ok = ctx.net_edge is not None and ctx.net_edge >= edge_need
    checks.append(
        _check(
            L.LOCKED_LABELS[3],
            late_ok,
            "unknown"
            if ctx.net_edge is None
            else f"{ctx.net_edge * 100:+.1f}¢ need {edge_need * 100:.1f}¢"
            + (" (+2¢ late)" if need_extra else ""),
            locked=True,
        )
    )
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


def strategy_checks(kind: str, ctx: GateContext) -> list[dict]:
    checks: list[dict] = []
    spread = None if ctx.ask is None or ctx.bid is None else ctx.ask - ctx.bid
    edge_s = "unknown" if ctx.net_edge is None else f"{ctx.net_edge * 100:+.1f}¢"

    if kind == "gates":
        need = float(ctx.params.get("net_edge_min", 0.02))
        checks.append(_check("Net edge", ctx.net_edge is not None and ctx.net_edge >= need, edge_s))
        t_ok, t_d = _trend_sigma_ok(ctx)
        checks.append(_check("Trend σ", t_ok, t_d))
        agrees = ctx.momentum is not None and ctx.momentum > 0
        checks.append(
            _check("Momentum agrees", agrees, "flat" if not ctx.momentum else ("with" if agrees else "against"))
        )
        flow_need = float(ctx.params.get("flow_min", 0.58)) * 100
        flow_ok = ctx.flow_pct is not None and ctx.flow_pct >= flow_need
        checks.append(
            _check("Taker flow", flow_ok, "unknown" if ctx.flow_pct is None else f"{ctx.flow_pct:.0f}%")
        )
        vmin = float(ctx.params.get("vol_min", 0.5))
        vmax = float(ctx.params.get("vol_max", 2.0))
        vol_ok = ctx.vol_ratio is not None and vmin <= ctx.vol_ratio <= vmax
        checks.append(
            _check(
                "Vol band",
                vol_ok,
                "unknown" if ctx.vol_ratio is None else f"{ctx.vol_ratio:.2f}× ({vmin}–{vmax})",
            )
        )
        floor = float(ctx.params.get("ask_floor", 0.35))
        cap = float(ctx.params.get("ask_cap", 0.65))
        band_ok = ctx.ask is not None and floor <= ctx.ask <= cap
        checks.append(
            _check("Ask band", band_ok, "unknown" if ctx.ask is None else f"{ctx.ask * 100:.0f}¢")
        )
        sm = float(ctx.params.get("spread_max", 0.03))
        sp_ok = spread is not None and spread <= sm
        checks.append(_check("Spread", sp_ok, "unknown" if spread is None else f"{spread * 100:.1f}¢"))
        return checks

    if kind == "arb":
        window = (
            ctx.secs_left is not None and L.ARB_WINDOW_MIN <= ctx.secs_left <= L.ARB_WINDOW_MAX
        )
        checks.append(
            _check("Arb window", window, "unknown" if ctx.secs_left is None else f"{ctx.secs_left:.0f}s")
        )
        stale = False
        stale_d = "n/a"
        if ctx.composite_pct_move_3s is not None and ctx.kalshi_mid_move_3s is not None:
            stale = ctx.composite_pct_move_3s >= L.ARB_STALE_COMPOSITE_PCT and abs(ctx.kalshi_mid_move_3s) < 1e-6
            stale_d = f"comp {ctx.composite_pct_move_3s * 100:.3f}% · mid Δ{ctx.kalshi_mid_move_3s * 100:.3f}%"
        checks.append(_check("Stale quote trigger", stale, stale_d))
        floor = float(ctx.params.get("ask_floor", 0.35))
        cap = float(ctx.params.get("ask_cap", 0.65))
        band_ok = ctx.ask is not None and floor <= ctx.ask <= cap
        checks.append(_check("Ask band", band_ok, "unknown" if ctx.ask is None else f"{ctx.ask * 100:.0f}¢"))
        pad = L.ARB_PAD_BASE + (L.ARB_PAD_VOL if (ctx.vol_ratio or 0) > L.ARB_VOL_HOT else 0)
        need = None if spread is None else spread + pad
        edge_ok = ctx.net_edge is not None and need is not None and ctx.net_edge >= need
        checks.append(
            _check(
                "Edge vs spread+pad",
                edge_ok,
                edge_s if need is None else f"{edge_s} vs {need * 100:.1f}¢",
            )
        )
        sm = float(ctx.params.get("spread_max", 0.03))
        checks.append(_check("Spread", spread is not None and spread <= sm, "unknown" if spread is None else ""))
        return checks

    if kind == "sol":
        if ctx.asset != "SOL":
            return [_check("SOL only", False, ctx.asset)]
        band_ok = ctx.ask is not None and L.SOL_ASK_MIN <= ctx.ask <= L.SOL_ASK_MAX
        checks.append(_check("Ask band", band_ok, "unknown" if ctx.ask is None else f"{ctx.ask * 100:.0f}¢"))
        checks.append(
            _check(
                "Net edge",
                ctx.net_edge is not None and ctx.net_edge >= L.SOL_NET_EDGE_MIN,
                edge_s,
            )
        )
        t_ok, t_d = _trend_sigma_ok(ctx)
        agrees = ctx.momentum is not None and ctx.momentum > 0
        prob_ok = ctx.prob is not None and ctx.prob >= 0.5
        checks.append(_check("Trend + momentum", t_ok and agrees and prob_ok, t_d))
        btc_ok = ctx.btc_momentum is None or (ctx.btc_momentum > 0 and agrees) or (ctx.btc_momentum < 0 and not agrees)
        checks.append(_check("BTC confirms", btc_ok, "BTC mom aligned" if btc_ok else "BTC disagrees"))
        chase = ctx.vol_ratio is not None and ctx.vol_ratio > 2.2 and ctx.momentum is not None and ctx.momentum != 0
        checks.append(_check("Spike/chase filter", not chase, "spike" if chase else "ok"))
        confirm_ok = ctx.sol_confirm_secs is not None and ctx.sol_confirm_secs >= L.SOL_CONFIRM_SECS
        checks.append(
            _check(
                "3s entry confirm",
                confirm_ok,
                "unknown" if ctx.sol_confirm_secs is None else f"{ctx.sol_confirm_secs:.1f}s",
            )
        )
        return checks

    if kind == "scanner":
        cheap = ctx.ask is not None and ctx.ask <= L.SUB25_ASK_MAX
        checks.append(_check("Ask ≤25¢", cheap, "unknown" if ctx.ask is None else f"{ctx.ask * 100:.1f}¢"))
        checks.append(
            _check(
                "Net edge",
                ctx.net_edge is not None and ctx.net_edge >= L.SUB25_EDGE_MIN,
                edge_s,
            )
        )
        outside = ctx.secs_left is not None and ctx.secs_left > L.SUB25_BLACKOUT
        checks.append(_check("Outside last 2m", outside, "unknown" if ctx.secs_left is None else f"{ctx.secs_left:.0f}s"))
        if ctx.momentum is not None and ctx.momentum > 0:
            checks.append(_check("Breakout (YES only)", ctx.side == "UP", "YES breakout lane"))
        elif ctx.momentum is not None and ctx.momentum < 0:
            checks.append(_check("Exhaustion (NO only)", ctx.side == "DOWN", "NO exhaustion lane"))
        else:
            checks.append(_check("Breakout / exhaustion", False, "flat momentum"))
        checks.append(_check("Log only", True, "not wired to paper"))
        return checks

    return [_check("Strategy", False, kind or "unknown")]


def evaluate_side(
    *,
    strategy: dict,
    ctx_base: GateContext,
    fee_fn: Callable[[float], float],
) -> list[dict]:
    kind = strategy.get("kind")
    if kind == "hour":
        return [_check("15m desk only", False, "use 1h product")]
    locked = locked_checks(ctx_base)
    strat = strategy_checks(kind, ctx_base)
    return locked + strat


def all_pass(checks: list[dict]) -> bool:
    return bool(checks) and all(c["ok"] for c in checks)
