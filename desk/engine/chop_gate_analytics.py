"""Chop gate candidate + shadow trade reporting."""
from __future__ import annotations

from desk.engine.chop_gates import DEFAULTS as CHOP_GATE_DEFAULTS


def _tier_label(score: float | None, prefs: dict) -> str:
    if score is None:
        return "unknown"
    low = float(prefs.get("tier_low_max", CHOP_GATE_DEFAULTS["tier_low_max"]))
    mid = float(prefs.get("tier_mid_max", CHOP_GATE_DEFAULTS["tier_mid_max"]))
    if score < low:
        return f"<{low:.0f}"
    if score < mid:
        return f"{low:.0f}-{mid:.0f}"
    return f">={mid:.0f}"


def _agg(rows: list[dict]) -> dict:
    settled = [r for r in rows if r.get("net_pnl") is not None and r.get("right") is not None]
    if not settled:
        return {"count": len(rows), "win_rate": None, "net_pnl": 0.0, "n_settled": 0}
    wins = sum(1 for r in settled if r.get("right"))
    pnl = sum(float(r["net_pnl"]) for r in settled)
    return {
        "count": len(rows),
        "n_settled": len(settled),
        "win_rate": wins / len(settled),
        "net_pnl": round(pnl, 4),
    }


def enrich_taken_trades(candidates: list[dict], paper_trades: list[dict]) -> list[dict]:
    """Attach chop scores from taken candidate logs to settled paper trades."""
    chop_by = {}
    for c in candidates:
        if not c.get("taken"):
            continue
        chop_by[(c.get("ticker"), c.get("side"), c.get("strategy"))] = c
    out = []
    for t in paper_trades:
        if not t.get("settled"):
            continue
        key = (t.get("ticker"), t.get("side"), t.get("strategy"))
        c = chop_by.get(key)
        out.append({**t, "chop": c.get("chop") if c else None})
    return out


def chop_gate_analytics(
    candidates: list[dict],
    shadows: list[dict],
    taken_trades: list[dict],
    *,
    chop_prefs: dict | None = None,
) -> dict:
    prefs = chop_prefs or CHOP_GATE_DEFAULTS
    taken_c = [c for c in candidates if c.get("taken")]
    blocked_c = [c for c in candidates if not c.get("taken") and c.get("would_have_entered")]
    shadow_settled = [s for s in shadows if s.get("settled") and s.get("net_pnl") is not None]

    taken_agg = _agg([{**t, "right": t.get("right"), "net_pnl": t.get("net_pnl")} for t in taken_trades])
    shadow_agg = _agg(shadow_settled)

    pnl_with_gate = taken_agg.get("net_pnl") or 0.0
    pnl_without = pnl_with_gate + sum(float(s.get("net_pnl") or 0) for s in shadow_settled)
    gate_improved = pnl_with_gate > pnl_without

    by_tier_strategy: dict[str, dict[str, dict]] = {}
    by_tier_asset: dict[str, dict[str, dict]] = {}

    def bump(nested: dict, key1: str, key2: str, row: dict, *, shadow: bool) -> None:
        nested.setdefault(key1, {})
        cell = nested[key1].setdefault(key2, {"taken": [], "shadow": []})
        bucket = "shadow" if shadow else "taken"
        cell[bucket].append(row)

    for t in taken_trades:
        tier = _tier_label(t.get("chop"), prefs)
        strat = t.get("strategy") or "unknown"
        asset = t.get("asset") or "?"
        bump(by_tier_strategy, strat, tier, t, shadow=False)
        bump(by_tier_asset, asset, tier, t, shadow=False)
    for s in shadow_settled:
        tier = _tier_label(s.get("chop"), prefs)
        strat = s.get("strategy") or "unknown"
        asset = s.get("asset") or "?"
        bump(by_tier_strategy, strat, tier, s, shadow=True)
        bump(by_tier_asset, asset, tier, s, shadow=True)

    def finalize(nested: dict) -> dict:
        out = {}
        for k1, inner in nested.items():
            out[k1] = {}
            for tier, buckets in inner.items():
                t_rows = buckets["taken"]
                s_rows = buckets["shadow"]
                t_a = _agg(t_rows)
                s_a = _agg(s_rows)
                n = t_a["n_settled"] + s_a["n_settled"]
                out[k1][tier] = {
                    "taken": t_a,
                    "shadow": s_a,
                    "n": n,
                    "low_n": n < 30,
                }
        return out

    by_strategy: dict[str, dict] = {}
    for strat in set(
        [t.get("strategy") for t in taken_trades if t.get("strategy")]
        + [s.get("strategy") for s in shadow_settled if s.get("strategy")]
    ):
        t_rows = [t for t in taken_trades if t.get("strategy") == strat]
        s_rows = [s for s in shadow_settled if s.get("strategy") == strat]
        t_pnl = sum(float(r.get("net_pnl") or 0) for r in t_rows if r.get("net_pnl") is not None)
        s_pnl = sum(float(r.get("net_pnl") or 0) for s in s_rows)
        by_strategy[strat] = {
            "taken": _agg(t_rows),
            "shadow": _agg(s_rows),
            "pnl_with_gate": round(t_pnl, 4),
            "pnl_without_gate": round(t_pnl + s_pnl, 4),
            "gate_improved_pnl": t_pnl > t_pnl + s_pnl,
        }

    return {
        "candidates_logged": len(candidates),
        "taken_candidates": len(taken_c),
        "blocked_candidates": len(blocked_c),
        "taken_trades": taken_agg,
        "shadow_trades": shadow_agg,
        "pnl_with_gate": round(pnl_with_gate, 4),
        "pnl_without_gate": round(pnl_without, 4),
        "gate_improved_total_pnl": gate_improved,
        "by_strategy": by_strategy,
        "by_chop_tier_strategy": finalize(by_tier_strategy),
        "by_chop_tier_asset": finalize(by_tier_asset),
        "chop_prefs": prefs,
    }
