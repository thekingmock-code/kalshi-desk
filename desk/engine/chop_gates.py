"""Three-layer chop gate system (paper only, log-first)."""
from __future__ import annotations

from dataclasses import dataclass

from desk.engine import locked as L
from desk.engine.gates_eval import gate_edge_value
from desk.engine.weekend_money import g4_requirements, raw_prob_edge_cents
from desk.engine.gates_eval import GateContext

CHOP_GATES_KEY = "chop_gates"

DEFAULTS = {
    "layer0_enabled": True,
    "feed_max_age_s": 2.0,
    "quote_max_age_s": 5.0,
    "max_missing_rows": 2,
    "soft_enabled": False,
    "tier_low_max": 30.0,
    "tier_mid_max": 50.0,
    "addon_below_low_cents": 2.0,
    "addon_mid_cents": 1.0,
    "hard_enabled": False,
    "chop_hard_min": 0.0,
}


def load_chop_gates(settings: dict) -> dict:
    raw = settings.get(CHOP_GATES_KEY) or {}
    out = dict(DEFAULTS)
    for k in out:
        if k in raw:
            out[k] = raw[k]
    out["layer0_enabled"] = bool(out["layer0_enabled"])
    out["soft_enabled"] = bool(out["soft_enabled"])
    out["hard_enabled"] = bool(out["hard_enabled"])
    out["feed_max_age_s"] = max(0.5, min(10.0, float(out["feed_max_age_s"])))
    out["quote_max_age_s"] = max(0.5, min(30.0, float(out["quote_max_age_s"])))
    out["max_missing_rows"] = max(0, min(3, int(out["max_missing_rows"])))
    out["tier_low_max"] = max(0.0, min(100.0, float(out["tier_low_max"])))
    out["tier_mid_max"] = max(out["tier_low_max"], min(100.0, float(out["tier_mid_max"])))
    out["chop_hard_min"] = max(0.0, min(60.0, float(out["chop_hard_min"])))
    return out


def chop_addon_cents(chop_score: float, prefs: dict) -> float:
    if not prefs.get("soft_enabled"):
        return 0.0
    low = float(prefs["tier_low_max"])
    mid = float(prefs["tier_mid_max"])
    if chop_score < low:
        return float(prefs["addon_below_low_cents"])
    if chop_score < mid:
        return float(prefs["addon_mid_cents"])
    return 0.0


def integrity_block(
    *,
    prefs: dict,
    feed_ages: dict | None,
    quote_age_s: float | None,
    chop_partial: bool,
    missing_rows: int,
) -> str | None:
    if not prefs.get("layer0_enabled"):
        return None
    max_feed = float(prefs["feed_max_age_s"])
    ages = feed_ages or {}
    cb = ages.get("coinbase")
    kr = ages.get("kraken")
    if cb is None or cb > max_feed:
        return "integrity:coinbase_stale"
    if kr is None or kr > max_feed:
        return "integrity:kraken_stale"
    max_q = float(prefs["quote_max_age_s"])
    if quote_age_s is None or quote_age_s > max_q:
        return "integrity:kalshi_quote_stale"
    if chop_partial and missing_rows > int(prefs["max_missing_rows"]):
        return "integrity:chop_partial"
    return None


def soft_edge_detail(
    *,
    strategy: dict,
    side: str,
    view: dict,
    prefs: dict,
    chop_score: float,
    addon_cents: float,
    is_weekend: bool,
) -> tuple[bool, str]:
    """Return (passes_after_soft, detail text fragment)."""
    if addon_cents <= 0:
        return True, ""
    bot = view.get("bot") or {}
    market = view.get("market") or {}
    params = view.get("tunable_params") or strategy.get("params") or {}
    modes = view.get("_paper_modes") or {}
    basis = modes.get("edge_basis", "net")
    if side == "UP":
        gate_edge = gate_edge_value(basis, bot.get("edge_up"), bot.get("edge_up_entry"))
    else:
        gate_edge = gate_edge_value(basis, bot.get("edge_down"), bot.get("edge_down_entry"))
    addon = addon_cents / 100.0
    late = 0.0
    secs = (view.get("trade") or {}).get("secs_left")
    if secs is not None and secs < L.LATE_SECS:
        late = L.LATE_EDGE_EXTRA
    weekend_bump = float(view.get("_weekend_bump_cents") or 0) / 100.0

    if strategy.get("kind") == "weekend_money":
        ctx = GateContext(
            asset=view.get("_asset") or "BTC",
            side=side,
            secs_left=secs,
            bid=None,
            ask=market.get("yes_ask") if side == "UP" else market.get("no_ask"),
            prob=bot.get("p_up") if side == "UP" else (None if bot.get("p_up") is None else 1 - bot["p_up"]),
            flow_pct=None,
            momentum=None,
            vol_ratio=None,
            sigma_t=None,
            ref=None,
            strike=market.get("strike"),
            dual_feed_ok=True,
            feed_detail="",
            p_up=bot.get("p_up"),
            yes_mid=market.get("yes_mid"),
            no_mid=market.get("no_mid"),
            net_edge=gate_edge,
            params=params,
            is_weekend=is_weekend,
        )
        need_c, base_c, bump_c = g4_requirements(ctx)
        need_c += addon_cents
        raw = raw_prob_edge_cents(ctx)
        ok = raw is not None and raw >= need_c
        detail = (
            f"required {need_c:.1f}c (base {base_c:.1f}c + late {late*100:.1f}c + "
            f"weekend {bump_c:.1f}c + chop {addon_cents:.1f}c)"
        )
        return ok, detail

    base_need = float(params.get("net_edge_min", 0.02)) + late + addon
    ok = gate_edge is not None and gate_edge >= base_need
    detail = (
        f"required {base_need*100:.1f}c (base {float(params.get('net_edge_min',0.02))*100:.1f}c + "
        f"late {late*100:.1f}c + weekend {weekend_bump*100:.1f}c + chop {addon_cents:.1f}c)"
    )
    return ok, detail


@dataclass
class ChopGateResult:
    allow_entry: bool
    gate_layer_result: str
    chop_addon_cents: float
    block_reason: str | None
    would_have_entered: bool
    soft_detail: str = ""


def evaluate_chop_gates(
    *,
    prefs: dict,
    would_have_entered: bool,
    chop_score: float,
    chop_partial: bool,
    missing_rows: int,
    feed_ages: dict | None,
    quote_age_s: float | None,
    strategy: dict,
    side: str,
    view: dict,
    is_weekend: bool,
) -> ChopGateResult:
    addon = chop_addon_cents(chop_score, prefs)
    if not would_have_entered:
        return ChopGateResult(
            allow_entry=False,
            gate_layer_result="passed",
            chop_addon_cents=addon,
            block_reason=None,
            would_have_entered=False,
        )
    reason = integrity_block(
        prefs=prefs,
        feed_ages=feed_ages,
        quote_age_s=quote_age_s,
        chop_partial=chop_partial,
        missing_rows=missing_rows,
    )
    if reason:
        return ChopGateResult(
            allow_entry=False,
            gate_layer_result="integrity_block",
            chop_addon_cents=addon,
            block_reason=reason,
            would_have_entered=True,
        )
    if prefs.get("hard_enabled") and chop_score < float(prefs["chop_hard_min"]):
        return ChopGateResult(
            allow_entry=False,
            gate_layer_result="hard_block",
            chop_addon_cents=addon,
            block_reason=f"chop_score {chop_score:.0f} < {prefs['chop_hard_min']:.0f}",
            would_have_entered=True,
        )
    soft_ok, soft_detail = soft_edge_detail(
        strategy=strategy,
        side=side,
        view=view,
        prefs=prefs,
        chop_score=chop_score,
        addon_cents=addon,
        is_weekend=is_weekend,
    )
    if prefs.get("soft_enabled") and addon > 0 and not soft_ok:
        return ChopGateResult(
            allow_entry=False,
            gate_layer_result="soft_raised",
            chop_addon_cents=addon,
            block_reason="soft_edge",
            would_have_entered=True,
            soft_detail=soft_detail,
        )
    return ChopGateResult(
        allow_entry=True,
        gate_layer_result="passed",
        chop_addon_cents=addon,
        block_reason=None,
        would_have_entered=True,
        soft_detail=soft_detail,
    )
