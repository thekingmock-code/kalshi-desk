"""Per-side gate checks. Values come from the active strategy params."""
from __future__ import annotations

from datetime import datetime, timezone


def _check(label: str, ok: bool, detail: str) -> dict:
    return {"label": label, "ok": bool(ok), "detail": detail}


def _edge(prob: float | None, ask: float | None, fee_fn) -> float | None:
    if prob is None or ask is None:
        return None
    return prob - ask - fee_fn(ask)


def gate_sides(
    strategy: dict,
    *,
    asset: str,
    secs_left: float | None,
    yes_bid: float | None,
    yes_ask: float | None,
    no_bid: float | None,
    no_ask: float | None,
    p_up: float | None,
    buy_pct: float | None,
    momentum: int | None,
    vol_ratio: float | None,
    now: float,
    fee_fn,
    already_entered_hour: bool = False,
) -> dict[str, list[dict]]:
    return {
        "UP": _one(
            strategy, "UP", asset, secs_left, yes_bid, yes_ask, p_up, buy_pct, momentum, vol_ratio, now, fee_fn, already_entered_hour
        ),
        "DOWN": _one(
            strategy,
            "DOWN",
            asset,
            secs_left,
            no_bid,
            no_ask,
            None if p_up is None else 1 - p_up,
            None if buy_pct is None else 100 - buy_pct,
            None if momentum is None else -momentum,
            vol_ratio,
            now,
            fee_fn,
            already_entered_hour,
        ),
    }


def _one(
    strategy,
    side,
    asset,
    secs_left,
    bid,
    ask,
    prob,
    flow_pct,
    momentum,
    vol_ratio,
    now,
    fee_fn,
    already_entered_hour,
) -> list[dict]:
    kind = strategy.get("kind")
    p = strategy.get("params") or {}
    checks: list[dict] = []
    edge = _edge(prob, ask, fee_fn)
    edge_s = "unknown" if edge is None else f"{edge * 100:+.1f}¢"
    spread = None if ask is None or bid is None else ask - bid

    if kind == "sol" and asset != "SOL":
        return [_check("SOL only", False, asset)]

    if kind == "gates":
        checks.append(_check("Trend edge", edge is not None and edge >= float(p["edge_min"]), edge_s))
        agrees = momentum is not None and momentum > 0
        checks.append(_check("Momentum agrees", agrees, "flat" if not momentum else ("with" if agrees else "against")))
        flow_ok = flow_pct is not None and flow_pct >= float(p["flow_min"]) * 100
        checks.append(_check("Taker flow", flow_ok, "unknown" if flow_pct is None else f"{flow_pct:.0f}%"))
        vol_ok = vol_ratio is not None and vol_ratio <= float(p["vol_max"])
        checks.append(_check("Vol regime", vol_ok, "unknown" if vol_ratio is None else f"{vol_ratio:.2f}×"))
        cap_ok = ask is not None and ask <= float(p["price_cap"])
        checks.append(_check("Price cap", cap_ok, "unknown" if ask is None else f"{ask * 100:.0f}¢"))
        time_ok = secs_left is not None and secs_left >= float(p["min_secs_left"])
        checks.append(_check("Expiry safeguard", time_ok, "unknown" if secs_left is None else f"{secs_left:.0f}s"))
        return checks

    if kind == "arb":
        window = secs_left is not None and float(p["secs_min"]) <= secs_left <= float(p["secs_max"])
        checks.append(_check("Entry window", window, "unknown" if secs_left is None else f"{secs_left:.0f}s"))
        band = ask is not None and float(p["price_min"]) <= ask <= float(p["price_max"])
        checks.append(_check("Price band", band, "unknown" if ask is None else f"{ask * 100:.0f}¢"))
        pad = float(p["pad_base"]) + (float(p["pad_vol"]) if (vol_ratio or 0) > float(p["vol_hot"]) else 0)
        need = None if spread is None else spread + pad
        edge_ok = edge is not None and need is not None and edge >= need
        checks.append(_check("Edge vs spread + pad", edge_ok, edge_s if need is None else f"{edge_s} vs {(need * 100):.1f}¢"))
        cap_ok = ask is not None and ask <= float(p["price_cap"])
        checks.append(_check("Price cap", cap_ok, "unknown" if ask is None else f"{ask * 100:.0f}¢"))
        return checks

    if kind == "sol":
        band = ask is not None and float(p["price_min"]) <= ask <= float(p["price_max"])
        checks.append(_check("Price band", band, "unknown" if ask is None else f"{ask * 100:.0f}¢"))
        time_ok = secs_left is not None and secs_left >= float(p["min_secs_left"])
        checks.append(_check("Time left", time_ok, "unknown" if secs_left is None else f"{secs_left:.0f}s"))
        checks.append(_check("Net edge", edge is not None and edge >= float(p["edge_min"]), edge_s))
        agrees = momentum is not None and momentum > 0
        checks.append(_check("Trend + momentum", agrees and prob is not None and prob >= 0.5, "needs momentum with the side"))
        return checks

    if kind == "hour":
        minute = datetime.fromtimestamp(now, timezone.utc).minute
        last = int(float(p["last_minutes"]))
        in_window = minute >= 60 - last
        checks.append(_check("Last minutes of the UTC hour", in_window, f"minute {minute}"))
        band = ask is not None and float(p["price_min"]) <= ask <= float(p["price_max"])
        checks.append(_check("Ask band", band, "unknown" if ask is None else f"{ask * 100:.0f}¢"))
        checks.append(_check("One entry this hour", not already_entered_hour, "already used" if already_entered_hour else "open"))
        return checks

    if kind == "scanner":
        cheap = ask is not None and ask < float(p["price_max"])
        checks.append(_check("Ask below cap", cheap, "unknown" if ask is None else f"{ask * 100:.1f}¢"))
        checks.append(_check("Net edge", edge is not None and edge >= float(p["edge_min"]), edge_s))
        outside = secs_left is not None and secs_left > float(p["blackout_secs"])
        checks.append(_check("Outside blackout", outside, "unknown" if secs_left is None else f"{secs_left:.0f}s"))
        checks.append(_check("Log only", True, "not an entry"))
        return checks

    return [_check("Strategy", False, kind or "unknown")]


def all_pass(checks: list[dict]) -> bool:
    return bool(checks) and all(c["ok"] for c in checks)
