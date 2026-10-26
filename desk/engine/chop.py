"""Hand-set chop-versus-real score. Weights are uncalibrated."""
from __future__ import annotations


def chop_score(
    *,
    lead: float | None,
    sigma_t: float | None,
    lag: float | None,
    leader: int | None,
    buy_pct: float | None,
    momentum: int | None,
    crossings: int,
    cfg: dict,
) -> tuple[float, list[dict]]:
    cushion_pts = 0.0
    if lead is not None and sigma_t and sigma_t > 0:
        cushion_pts = min(abs(lead) / sigma_t / float(cfg["cushion_div"]), 1.0) * float(cfg["cushion_max"])

    if lag is None or leader is None:
        lag_pts = float(cfg["lag_unknown"])
    elif lag * leader > 0:
        lag_pts = float(cfg["lag_points"])
    else:
        lag_pts = 0.0

    if buy_pct is None or leader is None:
        flow_pts = float(cfg["flow_unknown"])
    else:
        aligned = max((buy_pct - 50.0) * leader, 0.0)
        flow_pts = min(aligned / float(cfg["flow_scale"]), 1.0) * float(cfg["flow_max"])

    if momentum is None or momentum == 0 or leader is None:
        mom_pts = float(cfg["momentum_flat"])
    elif momentum * leader > 0:
        mom_pts = float(cfg["momentum_aligned"])
    else:
        mom_pts = float(cfg["momentum_against"])

    if crossings <= 0:
        cross_pts = float(cfg["crossings_0"])
    elif crossings == 1:
        cross_pts = float(cfg["crossings_1"])
    else:
        cross_pts = float(cfg["crossings_2plus"])

    parts = [
        {"name": "Cushion", "points": round(cushion_pts, 2), "max": cfg["cushion_max"]},
        {"name": "Composite vs index", "points": round(lag_pts, 2), "max": cfg["lag_points"]},
        {"name": "Taker flow", "points": round(flow_pts, 2), "max": cfg["flow_max"]},
        {"name": "Momentum", "points": round(mom_pts, 2), "max": cfg["momentum_aligned"]},
        {"name": "Strike crossings", "points": round(cross_pts, 2), "max": cfg["crossings_0"]},
    ]
    total = min(100.0, sum(p["points"] for p in parts))
    return total, parts


def chop_label(score: float, cfg: dict) -> str:
    if score >= float(cfg["real_min"]):
        return "REAL MOVE"
    if score >= float(cfg["mixed_min"]):
        return "MIXED"
    return "COIN FLIP"
