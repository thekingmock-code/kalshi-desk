"""Paper-only edge basis, negative floor, ignore-edge, and fade mode (15m Gates)."""
from __future__ import annotations

from desk.engine import locked as L
from desk.engine.gates_eval import all_pass, net_edge, net_edge_entry

PAPER_SETTINGS_KEY = "gates_15m_paper"

DIVERGENCE_LABEL = L.LOCKED_LABELS[2]
LATE_EDGE_LABEL = L.LOCKED_LABELS[3]
EDGE_GATE_LABELS = frozenset(
    {
        "Net edge",
        LATE_EDGE_LABEL,
        "G4 Prob edge",
    }
)

FADE_STRATEGY_KEEP = frozenset({"Ask band", "Spread"})


def default_paper_modes() -> dict:
    return {
        "edge_basis": "net",
        "min_net_edge_cents": 0.0,
        "ignore_edge_gate": False,
        "fade_model": False,
        "fade_trigger_cents": 10.0,
        "momentum_gate_enabled": True,
    }


def load_paper_modes(settings: dict) -> dict:
    raw = settings.get(PAPER_SETTINGS_KEY)
    out = default_paper_modes()
    if isinstance(raw, dict):
        for k in out:
            if k in raw:
                out[k] = raw[k]
    if out["edge_basis"] not in ("net", "entry"):
        out["edge_basis"] = "net"
    out["min_net_edge_cents"] = float(out["min_net_edge_cents"])
    out["fade_trigger_cents"] = float(out["fade_trigger_cents"])
    out["ignore_edge_gate"] = bool(out["ignore_edge_gate"])
    out["fade_model"] = bool(out["fade_model"])
    out["momentum_gate_enabled"] = bool(out.get("momentum_gate_enabled", True))
    out["min_net_edge_cents"] = max(-10.0, min(10.0, out["min_net_edge_cents"]))
    out["fade_trigger_cents"] = max(1.0, min(30.0, out["fade_trigger_cents"]))
    return out


def compute_edges(
    *,
    prob: float | None,
    ask: float | None,
    spread: float | None,
    yes_mid: float | None,
    side: str,
    fee_fn,
) -> dict:
    en = net_edge(prob, ask, spread, fee_fn)
    ee = net_edge_entry(prob, ask, fee_fn)
    pup = prob if side == "UP" else (None if prob is None else 1.0 - prob)
    mid = yes_mid if side == "UP" else None
    if side == "DOWN" and yes_mid is not None:
        mid = 1.0 - yes_mid if False else None  # use no_mid passed separately
    raw = None
    if pup is not None and mid is not None:
        raw = (pup - mid) * 100.0
    return {"edge_net": en, "edge_entry": ee, "raw_prob_edge": raw}


def raw_prob_edge_for_side(p_up: float | None, yes_mid: float | None, no_mid: float | None, side: str) -> float | None:
    if p_up is None:
        return None
    prob = p_up if side == "UP" else 1.0 - p_up
    mid = yes_mid if side == "UP" else no_mid
    if mid is None:
        return None
    return (prob - mid) * 100.0


def resolve_gate_mode(modes: dict) -> str:
    if modes.get("fade_model"):
        return "fade"
    if modes.get("ignore_edge_gate"):
        return "override"
    if float(modes.get("min_net_edge_cents", 0)) < 0:
        return "floor_neg"
    return "normal"


def gate_mode_label(mode: str) -> str | None:
    labels = {
        "fade": "FADE MODEL",
        "override": "IGNORE EDGE",
        "floor_neg": "NEG EDGE FLOOR",
    }
    return labels.get(mode)


def fade_triggered(p_up: float | None, yes_mid: float | None, trigger_cents: float) -> bool:
    if p_up is None or yes_mid is None:
        return False
    return abs(p_up - yes_mid) >= trigger_cents / 100.0


def pick_entry_side(
    *,
    edge_up: float | None,
    edge_down: float | None,
    modes: dict,
    p_up: float | None,
    yes_mid: float | None,
) -> tuple[str | None, str]:
    mode = resolve_gate_mode(modes)
    if modes.get("fade_model"):
        if not fade_triggered(p_up, yes_mid, float(modes["fade_trigger_cents"])):
            return None, mode
        if edge_down is not None and (edge_up is None or edge_down < edge_up):
            return "DOWN", mode
        if edge_up is not None:
            return "UP", mode
        return None, mode
    if edge_down is not None and (edge_up is None or edge_down > edge_up):
        return "DOWN", mode
    if edge_up is not None:
        return "UP", mode
    return None, mode


def filter_checks_for_paper(checks: list[dict], *, modes: dict, strategy_kind: str) -> list[dict]:
    """Mark edge/divergence checks pass when modes allow (for paper entry evaluation)."""
    ignore = bool(modes.get("ignore_edge_gate"))
    fade = bool(modes.get("fade_model"))
    keep_locked = {L.LOCKED_LABELS[0], L.LOCKED_LABELS[1]}
    out = []
    for c in checks:
        label = c.get("label") or ""
        locked = bool(c.get("locked"))
        ok = c.get("ok")
        if ignore and label in EDGE_GATE_LABELS:
            ok = True
        if fade and label == DIVERGENCE_LABEL:
            ok = True
        if fade and label in EDGE_GATE_LABELS or (fade and label == LATE_EDGE_LABEL):
            ok = True
        if fade and strategy_kind == "gates":
            if locked and label not in keep_locked and label not in (DIVERGENCE_LABEL, LATE_EDGE_LABEL):
                ok = c.get("ok")
            elif not locked and label not in FADE_STRATEGY_KEEP:
                ok = True
        out.append({**c, "ok": ok})
    return out


def paper_gates_pass(checks: list[dict], *, modes: dict, strategy_kind: str) -> bool:
    filtered = filter_checks_for_paper(checks, modes=modes, strategy_kind=strategy_kind)
    return all_pass(filtered)


def paper_edge_floor_ok(
    gate_edge: float | None,
    modes: dict,
) -> bool:
    if modes.get("ignore_edge_gate"):
        return True
    if gate_edge is None:
        return False
    need = float(modes.get("min_net_edge_cents", 0)) / 100.0
    return gate_edge >= need


def entry_snapshot(
    *,
    side: str,
    bot: dict,
    market: dict,
    p_up: float | None,
    yes_mid: float | None,
    no_mid: float | None,
    secs_left: float | None,
    fee_fn,
    gate_mode: str,
    is_weekend: bool = False,
    weekend_bump_applied: float = 0.0,
    strategy_id: str | None = None,
    hour_et: int | None = None,
    session: str | None = None,
) -> dict:
    ask = market.get("yes_ask") if side == "UP" else market.get("no_ask")
    bid = market.get("yes_bid") if side == "UP" else market.get("no_bid")
    spread = None if ask is None or bid is None else ask - bid
    prob = p_up if side == "UP" else (None if p_up is None else 1.0 - p_up)
    en = net_edge(prob, ask, spread, fee_fn)
    ee = net_edge_entry(prob, ask, fee_fn)
    raw = raw_prob_edge_for_side(p_up, yes_mid, no_mid, side)
    fee = fee_fn(ask) if ask is not None else None
    return {
        "gate_mode": gate_mode,
        "edge_net": en,
        "edge_entry": ee,
        "raw_prob_edge": raw,
        "p_up": p_up,
        "ask": ask,
        "fee": fee,
        "spread": spread,
        "secs_left": secs_left,
        "is_weekend": bool(is_weekend),
        "weekend_bump_applied": float(weekend_bump_applied),
        "strategy": strategy_id,
        "hour_et": hour_et,
        "session": session,
    }


def edge_bucket_cents(edge_net: float | None) -> str:
    if edge_net is None:
        return "unknown"
    c = edge_net * 100.0
    if c < -4:
        return "<-4c"
    if c < 0:
        return "-4to0"
    if c < 2:
        return "0to2"
    return "2plus"


def _stats(subset: list[dict]) -> dict:
    if not subset:
        return {"count": 0, "win_rate": None, "net_pnl": 0.0}
    wins = sum(1 for r in subset if (r.get("net_pnl") or 0) > 0 or r.get("right"))
    return {
        "count": len(subset),
        "win_rate": wins / len(subset),
        "net_pnl": sum((r.get("net_pnl") or 0) for r in subset),
    }


def _weekend_period(r: dict) -> str:
    return "weekend" if r.get("is_weekend") else "weekday"


def paper_trade_analytics(rows: list[dict]) -> dict:
    settled = [r for r in rows if r.get("settled") and r.get("net_pnl") is not None]

    def bucket_stats(key: str) -> dict:
        buckets = {"<-4c": [], "-4to0": [], "0to2": [], "2plus": [], "unknown": []}
        for r in settled:
            b = r.get(key) or edge_bucket_cents(r.get("edge_net"))
            buckets.setdefault(b, []).append(r)
        out = {}
        for name, subset in buckets.items():
            if not subset:
                out[name] = {
                    "count": 0,
                    "win_rate": None,
                    "net_pnl": 0.0,
                    "weekday": _stats([]),
                    "weekend": _stats([]),
                }
                continue
            wd = [r for r in subset if _weekend_period(r) == "weekday"]
            we = [r for r in subset if _weekend_period(r) == "weekend"]
            out[name] = {**_stats(subset), "weekday": _stats(wd), "weekend": _stats(we)}
        return out

    by_edge = bucket_stats("edge_bucket")
    by_mode: dict[str, dict] = {}
    for r in settled:
        m = r.get("gate_mode") or "normal"
        by_mode.setdefault(m, []).append(r)
    mode_stats = {}
    for m, subset in by_mode.items():
        wd = [r for r in subset if _weekend_period(r) == "weekday"]
        we = [r for r in subset if _weekend_period(r) == "weekend"]
        mode_stats[m] = {**_stats(subset), "weekday": _stats(wd), "weekend": _stats(we)}

    by_period = {
        "weekday": _stats([r for r in settled if _weekend_period(r) == "weekday"]),
        "weekend": _stats([r for r in settled if _weekend_period(r) == "weekend"]),
    }

    cal: dict[str, dict] = {}
    for r in settled:
        pup = r.get("p_up")
        if pup is None or r.get("up_won") is None:
            continue
        bucket = int(min(9, max(0, pup * 10))) * 10
        label = f"{bucket}-{bucket + 10}%"
        cal.setdefault(label, {"n": 0, "yes_rate": 0.0})
        cal[label]["n"] += 1
        cal[label]["yes_rate"] += float(r["up_won"])
    cal_table = []
    for label in sorted(cal.keys(), key=lambda x: int(x.split("-")[0])):
        row = cal[label]
        n = row["n"]
        cal_table.append(
            {
                "bucket": label,
                "n": n,
                "avg_p_up": None,
                "yes_settle_rate": (row["yes_rate"] / n) if n else None,
            }
        )
    for r in settled:
        if r.get("p_up") is None:
            continue
        bucket = int(min(9, max(0, r["p_up"] * 10))) * 10
        label = f"{bucket}-{bucket + 10}%"
        for row in cal_table:
            if row["bucket"] == label:
                break
    # fix avg p_up
    sums: dict[str, list[float]] = {}
    for r in settled:
        if r.get("p_up") is None:
            continue
        bucket = int(min(9, max(0, r["p_up"] * 10))) * 10
        label = f"{bucket}-{bucket + 10}%"
        sums.setdefault(label, []).append(float(r["p_up"]))
    for row in cal_table:
        pts = sums.get(row["bucket"], [])
        row["avg_p_up"] = sum(pts) / len(pts) if pts else None

    def group_by(field: str) -> dict[str, dict]:
        out: dict[str, list] = {}
        for r in settled:
            key = r.get(field)
            if key is None or key == "":
                key = "unknown"
            out.setdefault(str(key), []).append(r)
        return {k: _stats(v) for k, v in sorted(out.items())}

    by_strategy = group_by("strategy")
    by_session = group_by("session")
    by_hour: dict[str, dict] = {}
    for r in settled:
        h = r.get("hour_et")
        label = "unknown" if h is None else f"{int(h):02d}:00 ET"
        by_hour.setdefault(label, []).append(r)
    by_hour = {k: _stats(v) for k, v in sorted(by_hour.items())}

    return {
        "by_edge_bucket": by_edge,
        "by_gate_mode": mode_stats,
        "by_period": by_period,
        "by_strategy": by_strategy,
        "by_session": by_session,
        "by_hour": by_hour,
        "calibration": cal_table,
    }
