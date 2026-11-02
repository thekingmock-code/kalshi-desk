"""Exit rule vs hold-to-settlement reports."""
from __future__ import annotations

from collections import defaultdict
from typing import Any

MIN_TRADES = 100


def exit_rule_report(rows: list[dict]) -> dict[str, Any]:
    """
    rows: paper_exit_log entries with exit_rule, actual_pnl, settlement_pnl, entry_ask
    """
    by_rule: dict[str, list] = defaultdict(list)
    for r in rows:
        rule = r.get("exit_rule") or "unknown"
        by_rule[rule].append(r)

    out: dict[str, Any] = {}
    for rule, trades in by_rule.items():
        n = len(trades)
        saved = []
        wins = 0
        buckets: dict[str, list] = defaultdict(list)
        for t in trades:
            actual = t.get("actual_pnl")
            settle = t.get("settlement_pnl")
            if actual is not None and settle is not None:
                saved.append(float(settle) - float(actual))
            if actual is not None and float(actual) > 0:
                wins += 1
            ask = t.get("entry_ask")
            bucket = "?"
            if ask is not None:
                if ask < 0.35:
                    bucket = "<35c"
                elif ask < 0.55:
                    bucket = "35-55c"
                elif ask < 0.75:
                    bucket = "55-75c"
                else:
                    bucket = "75c+"
            buckets[bucket].append(t)
        avg_saved = sum(saved) / len(saved) if saved else None
        out[rule] = {
            "times_fired": n,
            "win_rate": wins / n if n else None,
            "avg_pnl_vs_hold": avg_saved,
            "insufficient_data": n < MIN_TRADES,
            "by_entry_bucket": {b: len(v) for b, v in buckets.items()},
        }
    return out
