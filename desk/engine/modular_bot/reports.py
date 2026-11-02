"""Strategy reports from bot decision / fill logs."""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def _breakeven_wr(avg_entry: float | None, fee_rate: float = 0.07) -> float | None:
    if avg_entry is None or avg_entry <= 0 or avg_entry >= 1:
        return None
    # Approx break-even win rate for binary at entry price with taker fee on win
    fee = fee_rate * avg_entry * (1 - avg_entry)
    return avg_entry + fee


def strategy_report(rows: list[dict], *, min_trades_live: int = 200) -> dict[str, Any]:
    """
    rows: settled trades with keys strategy, net_pnl, won, entry_ask, hour_et, asset
    """
    by_strat: dict[str, list] = defaultdict(list)
    for r in rows:
        for sid in r.get("strategies") or [r.get("strategy") or "unknown"]:
            by_strat[sid].append(r)

    out: dict[str, Any] = {}
    for sid, trades in by_strat.items():
        n = len(trades)
        wins = sum(1 for t in trades if t.get("won"))
        pnl = sum(float(t.get("net_pnl") or 0) for t in trades)
        entries = [t.get("entry_ask") for t in trades if t.get("entry_ask") is not None]
        avg_entry = sum(entries) / len(entries) if entries else None
        be = _breakeven_wr(avg_entry)
        wr = wins / n if n else None
        by_hour: dict[str, dict] = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0})
        by_bucket: dict[str, dict] = defaultdict(lambda: {"n": 0, "wins": 0, "pnl": 0.0})
        for t in trades:
            h = str(t.get("hour_et") or "?")
            by_hour[h]["n"] += 1
            by_hour[h]["wins"] += 1 if t.get("won") else 0
            by_hour[h]["pnl"] += float(t.get("net_pnl") or 0)
            b = t.get("price_bucket") or "?"
            by_bucket[b]["n"] += 1
            by_bucket[b]["wins"] += 1 if t.get("won") else 0
            by_bucket[b]["pnl"] += float(t.get("net_pnl") or 0)
        out[sid] = {
            "trades": n,
            "win_rate": wr,
            "breakeven_win_rate": be,
            "net_pnl": pnl,
            "eligible_for_live": n >= min_trades_live and pnl > 0,
            "by_hour": dict(by_hour),
            "by_price_bucket": dict(by_bucket),
        }
    return out
