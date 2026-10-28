"""Feature terciles and price-bucket calibration (paper, log-only)."""
from __future__ import annotations

import json
from typing import Any


def _stats(rows: list[dict]) -> dict:
    if not rows:
        return {"count": 0, "win_rate": None, "net_pnl": 0.0}
    wins = sum(1 for r in rows if (r.get("net_pnl") or 0) > 0 or r.get("right"))
    return {
        "count": len(rows),
        "win_rate": wins / len(rows),
        "net_pnl": sum((r.get("net_pnl") or 0) for r in rows),
    }


def _parse_meas(row: dict) -> dict:
    raw = row.get("meas_json")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


def ask_price_bucket(ask: float | None) -> str:
    if ask is None:
        return "unknown"
    c = ask * 100.0
    if c < 10:
        return "<10c"
    if c < 25:
        return "10-25c"
    if c < 40:
        return "25-40c"
    if c < 55:
        return "40-55c"
    if c < 70:
        return "55-70c"
    return "70c+"


def price_bucket_report(rows: list[dict]) -> dict:
    settled = [r for r in rows if r.get("settled") and r.get("net_pnl") is not None]
    out: dict[str, dict] = {}
    for r in settled:
        b = ask_price_bucket(r.get("ask"))
        strat = r.get("strategy") or "unknown"
        period = "weekend" if r.get("is_weekend") else "weekday"
        key = f"{b}|{strat}|{period}"
        out.setdefault(key, []).append(r)
    table = []
    for key, subset in sorted(out.items()):
        b, strat, period = key.split("|", 2)
        implied = None
        asks = [float(x["ask"]) for x in subset if x.get("ask") is not None]
        if asks:
            implied = sum(asks) / len(asks)
        st = _stats(subset)
        table.append(
            {
                "bucket": b,
                "strategy": strat,
                "period": period,
                "implied_ask": implied,
                **st,
            }
        )
    return {"rows": table}


def _nested_get(d: dict, path: str) -> Any:
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return None
        cur = cur.get(part)
    return cur


FEATURE_PATHS = [
    ("settlement.p_up_avgmodel", "P(up) avg model"),
    ("settlement.avg_vs_strike", "Avg vs strike"),
    ("settlement.locked_frac", "Locked frac"),
    ("book.book_imbalance", "Book imbalance"),
    ("book.quote_lag_ms", "Quote lag ms"),
    ("book.trade_volume_60s", "Trade vol 60s"),
    ("window.strike_crosses", "Strike crosses"),
    ("window.src_disagree_usd", "Src disagree USD"),
]


def _tercile_labels(values: list[float]) -> list[tuple[float, float, str]]:
    if len(values) < 3:
        return []
    s = sorted(values)
    n = len(s)
    i1 = n // 3
    i2 = 2 * n // 3
    t1, t2 = s[i1], s[i2]
    return [(float("-inf"), t1, "low"), (t1, t2, "mid"), (t2, float("inf"), "high")]


def feature_tercile_report(rows: list[dict]) -> dict:
    settled = [r for r in rows if r.get("settled") and r.get("net_pnl") is not None]
    by_feature: dict[str, list] = {}
    for path, label in FEATURE_PATHS:
        by_strategy: dict[str, list[float]] = {}
        for r in settled:
            meas = _parse_meas(r)
            val = _nested_get(meas, path)
            if val is None:
                continue
            strat = r.get("strategy") or "unknown"
            by_strategy.setdefault(strat, []).append((float(val), r))
        strat_out = {}
        for strat, pairs in by_strategy.items():
            vals = [p[0] for p in pairs]
            bands = _tercile_labels(vals)
            if not bands:
                continue
            buckets = []
            for lo, hi, name in bands:
                sub = [r for v, r in pairs if lo <= v < hi or (name == "high" and v >= lo)]
                buckets.append({"tercile": name, **_stats(sub)})
            strat_out[strat] = buckets
        if strat_out:
            by_feature[label] = strat_out
    return by_feature


def measurement_analytics(rows: list[dict]) -> dict:
    return {
        "price_buckets": price_bucket_report(rows),
        "feature_terciles": feature_tercile_report(rows),
    }
