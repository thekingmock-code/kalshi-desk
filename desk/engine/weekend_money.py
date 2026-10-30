"""THE WEEKEND MONEY — Brati-style six-gate 15m entry stack."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from desk.engine.gate_utils import all_active_pass, checks_excluding_labels, gate_check
from desk.engine.gates_eval import GateContext, _trend_sigma_ok
from desk.engine.model import fee_dollars

WARMUP_SECS = 180.0
ENTRY_SECS_MIN = 120.0
ENTRY_SECS_MAX = 720.0
SAFEGUARD_SECS = 60.0
FINAL_WINDOW_MIN = 60.0
FINAL_WINDOW_MAX = 120.0

SPIKE_KALSHI_PP = 0.05
SPIKE_INDEX_USD = 15.0

TREND_SIGMA_DEFAULT = {"BTC": 0.30, "SOL": 0.30, "BNB": 0.32}
SPREAD_DEFAULT = {"BTC": 0.03, "SOL": 0.03, "BNB": 0.05}
ASK_FLOOR_DEFAULT = 0.38
ASK_CAP_DEFAULT = 0.55
MIN_ASK_NORMAL = 0.20
SIGNAL_HOLD_SECS = 2.0

WEEKEND_PREFS_KEY = "weekend_prefs"


def is_weekend(ts: float | None = None, tz: str = "America/New_York") -> bool:
    zone = ZoneInfo(tz if tz in ("America/New_York", "UTC") else "America/New_York")
    when = datetime.now(zone) if ts is None else datetime.fromtimestamp(ts, zone)
    return when.weekday() >= 5


def load_weekend_prefs(settings: dict) -> dict:
    raw = settings.get(WEEKEND_PREFS_KEY) or {}
    tz = raw.get("timezone", "America/New_York")
    if tz not in ("America/New_York", "UTC"):
        tz = "America/New_York"
    g3 = raw.get("g3_settlement_enabled", True)
    if not isinstance(g3, bool):
        g3 = bool(g3)
    g4_cost = raw.get("g4_cost_adjusted_enabled", True)
    if not isinstance(g4_cost, bool):
        g4_cost = bool(g4_cost)
    try:
        pad = float(raw.get("g4_cost_pad_cents", 0.5))
    except (TypeError, ValueError):
        pad = 0.5
    pad = max(0.0, min(3.0, pad))
    return {
        "timezone": tz,
        "g3_settlement_enabled": g3,
        "g4_cost_adjusted_enabled": g4_cost,
        "g4_cost_pad_cents": pad,
    }


def weekend_bump_for_params(params: dict, *, is_weekend_flag: bool) -> float:
    if not is_weekend_flag:
        return 0.0
    return float(params.get("weekend_bump_cents", 0.0))


def g4_requirements(ctx: GateContext) -> tuple[float, float, float]:
    base = required_prob_edge_cents(ctx)
    bump = weekend_bump_for_params(ctx.params, is_weekend_flag=ctx.is_weekend)
    return base + bump, base, bump


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


def cost_adjusted_edge_cents(ctx: GateContext) -> float | None:
    raw = raw_prob_edge_cents(ctx)
    if raw is None or ctx.ask is None:
        return None
    spread = None if ctx.bid is None or ctx.ask is None else ctx.ask - ctx.bid
    fee_c = fee_dollars(1, ctx.ask, ctx.taker_rate) * 100.0
    half_spread_c = 0.0 if spread is None else (spread / 2.0) * 100.0
    return raw - fee_c - half_spread_c


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
    comp = ctx.composite_pct_move_3s
    mid = ctx.kalshi_mid_move_3s
    if comp is None or mid is None:
        return False, "n/a"
    kalshi_hot = abs(mid) >= SPIKE_KALSHI_PP
    index_calm = abs(comp) < 0.0005
    if kalshi_hot and index_calm:
        return True, f"Kalshi Δ{mid * 100:.1f}% · comp quiet"
    return False, "ok"


def weekend_checks(ctx: GateContext, *, ignore_edge_gates: bool = False) -> list[dict]:
    checks: list[dict] = []
    spread = None if ctx.ask is None or ctx.bid is None else ctx.ask - ctx.bid
    lag = ctx.lag

    t_ok, t_d = _trend_sigma_ok(ctx)
    mom30 = _mom_aligned(ctx.side, ctx.momentum_30)
    mom60 = _mom_aligned(ctx.side, ctx.momentum_60)
    drift_ok, drift_d = _spot_drift_ok(ctx.side, lag)
    g2 = t_ok and mom30 and mom60 and drift_ok
    checks.append(
        gate_check(
            "G2 Direction",
            ok=g2,
            detail=f"{t_d} · 30s/60s mom · {drift_d}",
            hardness="soft",
        )
    )

    if ctx.g3_settlement_enabled:
        if ctx.p_up is None:
            g3 = False
            g3d = "no P(up)"
        elif ctx.side == "UP":
            g3 = ctx.p_up >= 0.5
            g3d = f"P(up)={ctx.p_up * 100:.0f}% need ≥50%"
        else:
            g3 = ctx.p_up <= 0.5
            g3d = f"P(up)={ctx.p_up * 100:.0f}% need ≤50%"
        checks.append(gate_check("G3 Settlement view", ok=g3, detail=g3d, hardness="soft"))
    else:
        checks.append(
            gate_check(
                "G3 Settlement view",
                ok=False,
                detail="off",
                status="off",
                counts=False,
                hardness="soft",
            )
        )

    raw = raw_prob_edge_cents(ctx)
    need_c, base_c, bump_c = g4_requirements(ctx)
    cost_adj = cost_adjusted_edge_cents(ctx)
    margin = None if raw is None else raw - need_c
    g4 = ignore_edge_gates or (raw is not None and raw >= need_c)
    if ctx.g4_cost_adjusted_enabled and not ignore_edge_gates:
        pad = float(ctx.g4_cost_pad_cents)
        g4 = g4 and cost_adj is not None and cost_adj >= pad
    if raw is None:
        g4_detail = "unknown"
    else:
        margin_s = "unknown" if margin is None else f"{margin:+.1f}c"
        g4_detail = (
            f"margin vs required {margin_s} · raw {raw:+.1f}c · need {need_c:.1f}c "
            f"(base {base_c:.1f}c + weekend {bump_c:.1f}c)"
        )
        if cost_adj is not None:
            g4_detail += f" · cost-adjusted edge {cost_adj:+.1f}c"
            if ctx.g4_cost_adjusted_enabled:
                g4_detail += f" (pad {ctx.g4_cost_pad_cents:.1f}c)"
    checks.append(
        gate_check(
            "G4 Prob edge",
            ok=bool(g4),
            detail=g4_detail,
            hardness="hard",
            value=raw,
            threshold=need_c,
        )
    )

    floor = float(ctx.params.get("ask_floor", ASK_FLOOR_DEFAULT))
    cap = float(ctx.params.get("ask_cap", ASK_CAP_DEFAULT))
    sm = float(ctx.params.get("spread_max", SPREAD_DEFAULT.get(ctx.asset, 0.03)))
    band_ok = ctx.ask is not None and floor <= ctx.ask <= cap
    spread_ok = spread is not None and spread <= sm
    min_ask_ok = ctx.ask is not None and ctx.ask >= MIN_ASK_NORMAL
    g5 = band_ok and spread_ok and min_ask_ok
    checks.append(
        gate_check(
            "G5 Price band",
            ok=g5,
            detail="unknown"
            if ctx.ask is None
            else f"ask {ctx.ask * 100:.0f}¢ ({floor * 100:.0f}–{cap * 100:.0f}) · spread "
            + (f"{spread * 100:.1f}¢ ≤{sm * 100:.0f}¢" if spread is not None else "?"),
            hardness="hard",
        )
    )

    t_ok6, t_d6 = _timing_ok(ctx)
    checks.append(gate_check("G6 Timing (TTE)", ok=t_ok6, detail=t_d6, hardness="hard"))

    chase, chase_d = _spike_chase_block(ctx)
    checks.append(gate_check("Unified spike block", ok=not chase, detail=chase_d, hardness="hard"))

    pre_hold = checks_excluding_labels(checks, "Signal hold")
    others_pass = all_active_pass(pre_hold)

    hold_need = float(ctx.params.get("entry_hold_secs", SIGNAL_HOLD_SECS))
    if not others_pass:
        checks.append(
            gate_check(
                "Signal hold",
                ok=False,
                detail="waiting for other gates",
                status="waiting",
                counts=False,
                hardness="hard",
            )
        )
    else:
        hold_ok = ctx.signal_hold_secs is not None and ctx.signal_hold_secs >= hold_need
        checks.append(
            gate_check(
                "Signal hold",
                ok=hold_ok,
                detail="unknown"
                if ctx.signal_hold_secs is None
                else f"{ctx.signal_hold_secs:.1f}s / {hold_need:.0f}s",
                hardness="hard",
                value=ctx.signal_hold_secs,
                threshold=hold_need,
            )
        )

    return checks
