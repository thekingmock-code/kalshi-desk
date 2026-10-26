"""Hypothetical paper scores (observe-only). No orders."""
from __future__ import annotations

import json

from desk.engine.model import fee_dollars
from desk.engine.strategies import all_pass


def side_edge_and_ask(market: dict, bot: dict, side: str) -> tuple[float | None, float | None]:
    if side == "UP":
        return bot.get("edge_up"), market.get("yes_ask")
    return bot.get("edge_down"), market.get("no_ask")


def should_log_shadow(side: str, view: dict) -> bool:
    gates = (view.get("gates") or {}).get(side) or []
    if not all_pass(gates):
        return False
    edge, ask = side_edge_and_ask(view.get("market") or {}, view.get("bot") or {}, side)
    return edge is not None and edge > 0 and ask is not None and 0 < ask < 1


def settle_shadow_row(row: dict, settle_px: float | None, strike: float | None, taker_rate: float) -> dict:
    """Mark WIN/LOSS from composite vs strike at window end."""
    if settle_px is None or strike is None or row.get("entry_ask") is None:
        return {**row, "settled": 1, "settle_note": "missing settle price"}
    up_won = settle_px >= strike
    side = row["side"]
    win = (side == "YES" and up_won) or (side == "NO" and not up_won)
    exit_px = 1.0 if win else 0.0
    entry = float(row["entry_ask"])
    entry_fee = fee_dollars(1, entry, taker_rate)
    exit_fee = fee_dollars(1, exit_px, taker_rate) if exit_px > 0 else 0.0
    pnl = exit_px - entry - entry_fee - exit_fee
    return {
        **row,
        "settled": 1,
        "settle_composite": settle_px,
        "up_won": int(up_won),
        "right": int(win),
        "exit_px": exit_px,
        "net_pnl": round(pnl, 4),
        "settle_note": "approx composite vs strike",
    }


def calibration(rows: list[dict]) -> list[dict]:
    buckets = [
        (0, 20),
        (20, 30),
        (30, 40),
        (40, 50),
        (50, 60),
        (60, 70),
        (70, 80),
        (80, 100),
    ]
    settled = [r for r in rows if r.get("settled") and r.get("p_up") is not None and r.get("up_won") is not None]
    out = []
    for lo, hi in buckets:
        subset = [r for r in settled if lo <= float(r["p_up"]) * 100 < hi]
        if not subset:
            out.append({"label": f"{lo}-{hi}", "n": 0, "up_rate": None})
            continue
        up_rate = sum(int(r["up_won"]) for r in subset) / len(subset)
        out.append({"label": f"{lo}-{hi}", "n": len(subset), "up_rate": round(up_rate, 3)})
    return out


def gates_passed_labels(gates: list[dict]) -> str:
    ok = [g["label"] for g in gates if g.get("ok")]
    return ", ".join(ok)
