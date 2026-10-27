"""THE WEEKEND MONEY — Brati-style six-gate 15m entry stack."""
from __future__ import annotations

from desk.engine.gates_eval import GateContext, _check, _trend_sigma_ok

# 15m contract timing (900s total)
WARMUP_SECS = 180.0  # no entry first 3m → max 720s left
ENTRY_SECS_MIN = 120.0  # block last 2m
ENTRY_SECS_MAX = 720.0  # after warmup
SAFEGUARD_SECS = 60.0  # no new entries at or below this TTE
FINAL_WINDOW_MIN = 60.0
FINAL_WINDOW_MAX = 120.0

SPIKE_KALSHI_PP = 0.05  # 5pp / ~30s proxy via 3s move scaled
SPIKE_INDEX_USD = 15.0

TREND_SIGMA_DEFAULT = {"BTC": 0.30, "SOL": 0.30, "BNB": 0.32}
SPREAD_DEFAULT = {"BTC": 0.03, "SOL": 0.03, "BNB": 0.05}
ASK_FLOOR_DEFAULT = 0.38
ASK_CAP_DEFAULT = 0.55
MIN_ASK_NORMAL = 0.20
SIGNAL_HOLD_SECS = 2.0


def _mom_aligned(side: str, mom: int | None) -> bool:
    if mom is None or mom == 0:
        return False
    if side == "UP":
        return mom > 0
    return mom < 0


def _spot_drift_ok(side: str, lag: float | None) -> tuple[bool, str]:
    if lag is None:
        return False, "no lag"
    if side == "UP":
        ok = lag > 0
        return ok, f"lag {lag:+.2f} need >0"
    ok = lag < 0
    return ok, f"lag {lag:+.2f} need <0"


def required_prob_edge_cents(ctx: GateContext) -> float:
    """Dynamic edge in cents (fees not subtracted — model vs mid)."""
    base = float(ctx.params.get("prob_edge_min_cents", 3.0))
    secs = ctx.secs_left if ctx.secs_left is not None else 9999.0
    extra = 0.0
    if secs <= 120:
        extra += 2.0
    elif secs <= 300:
        extra += 1.0
    elif secs <= 600:
        extra += 0.5
    if FINAL_WINDOW_MIN < secs <= FINAL_WINDOW_MAX:
        extra += 1.0
    return base + extra


def raw_prob_edge_cents(ctx: GateContext) -> float | None:
    mid = ctx.yes_mid if ctx.side == "UP" else ctx.no_mid
    if ctx.prob is None or mid is None:
        return None
    return (ctx.prob - mid) * 100.0


def _timing_ok(ctx: GateContext) -> tuple[bool, str]:
    secs = ctx.secs_left
    if secs is None:
        return False, "unknown TTE"
    if secs <= SAFEGUARD_SECS:
        return False, f"{secs:.0f}s ≤ {SAFEGUARD_SECS:.0f}s safeguard"
    if secs < ENTRY_SECS_MIN:
        return False, f"{secs:.0f}s < {ENTRY_SECS_MIN:.0f}s min"
    if secs > ENTRY_SECS_MAX:
        return False, f"{secs:.0f}s > {ENTRY_SECS_MAX:.0f}s (warmup)"
    if FINAL_WINDOW_MIN < secs <= FINAL_WINDOW_MAX:
        return True, f"final window {secs:.0f}s"
    return True, f"{secs:.0f}s in band"


def _spike_chase_block(ctx: GateContext) -> tuple[bool, str]:
    """Block Kalshi-only chase spikes (composite calm, mid jumped)."""
    comp = ctx.composite_pct_move_3s
    mid = ctx.kalshi_mid_move_3s
    if comp is None or mid is None:
        return False, "n/a"
    kalshi_hot = abs(mid) >= SPIKE_KALSHI_PP
    index_calm = abs(comp) < 0.0005
    if kalshi_hot and index_calm:
        return True, f"Kalshi Δ{mid * 100:.1f}% · comp quiet"
    return False, "ok"


def weekend_checks(ctx: GateContext) -> list[dict]:
    checks: list[dict] = []
    spread = None if ctx.ask is None or ctx.bid is None else ctx.ask - ctx.bid
    lag = ctx.lag

    # Gate 2 — direction (trend σ + momentum + spot drift)
    t_ok, t_d = _trend_sigma_ok(ctx)
    mom30 = _mom_aligned(ctx.side, ctx.momentum_30)
    mom60 = _mom_aligned(ctx.side, ctx.momentum_60)
    drift_ok, drift_d = _spot_drift_ok(ctx.side, lag)
    g2 = t_ok and mom30 and mom60 and drift_ok
    checks.append(
        _check(
            "G2 Direction",
            g2,
            f"{t_d} · 30s/60s mom · {drift_d}",
        )
    )

    # Gate 3 — settlement view
    if ctx.p_up is None:
        g3 = False
        g3d = "no P(up)"
    elif ctx.side == "UP":
        g3 = ctx.p_up >= 0.5
        g3d = f"P(up)={ctx.p_up * 100:.0f}% need ≥50%"
    else:
        g3 = ctx.p_up <= 0.5
        g3d = f"P(up)={ctx.p_up * 100:.0f}% need ≤50%"
    checks.append(_check("G3 Settlement view", g3, g3d))

    # Gate 4 — probability edge (model − mid, cents)
    raw = raw_prob_edge_cents(ctx)
    need_c = required_prob_edge_cents(ctx)
    g4 = raw is not None and raw >= need_c
    checks.append(
        _check(
            "G4 Prob edge",
            g4,
            "unknown"
            if raw is None
            else f"{raw:+.1f}¢ vs {need_c:.1f}¢ need · net {ctx.net_edge * 100:+.1f}¢"
            if ctx.net_edge is not None
            else f"{raw:+.1f}¢ vs {need_c:.1f}¢ need",
        )
    )

    # Gate 5 — execution band
    floor = float(ctx.params.get("ask_floor", ASK_FLOOR_DEFAULT))
    cap = float(ctx.params.get("ask_cap", ASK_CAP_DEFAULT))
    sm = float(ctx.params.get("spread_max", SPREAD_DEFAULT.get(ctx.asset, 0.03)))
    band_ok = ctx.ask is not None and floor <= ctx.ask <= cap
    spread_ok = spread is not None and spread <= sm
    min_ask_ok = ctx.ask is not None and ctx.ask >= MIN_ASK_NORMAL
    g5 = band_ok and spread_ok and min_ask_ok
    checks.append(
        _check(
            "G5 Price band",
            g5,
            "unknown"
            if ctx.ask is None
            else f"ask {ctx.ask * 100:.0f}¢ ({floor * 100:.0f}–{cap * 100:.0f}) · spread "
            + (f"{spread * 100:.1f}¢ ≤{sm * 100:.0f}¢" if spread is not None else "?"),
        )
    )

    # Gate 6 — timing
    t_ok6, t_d6 = _timing_ok(ctx)
    checks.append(_check("G6 Timing (TTE)", t_ok6, t_d6))

    # Unified layer — spike chase block
    chase, chase_d = _spike_chase_block(ctx)
    checks.append(_check("Unified spike block", not chase, chase_d))

    hold_need = float(ctx.params.get("entry_hold_secs", SIGNAL_HOLD_SECS))
    hold_ok = ctx.signal_hold_secs is not None and ctx.signal_hold_secs >= hold_need
    checks.append(
        _check(
            "Signal hold",
            hold_ok,
            "unknown"
            if ctx.signal_hold_secs is None
            else f"{ctx.signal_hold_secs:.1f}s / {hold_need:.0f}s",
        )
    )

    return checks
