"""OBI reporting for Features tab (paper, log-only)."""
from __future__ import annotations

import json

from desk.engine.spot_obi import obi_bucket


def _stats(rows: list[dict]) -> dict:
    if not rows:
        return {"count": 0, "win_rate": None, "net_pnl": 0.0}
    wins = sum(1 for r in rows if (r.get("net_pnl") or 0) > 0 or r.get("right"))
    return {
        "count": len(rows),
        "win_rate": wins / len(rows),
        "net_pnl": sum((r.get("net_pnl") or 0) for r in rows),
    }


def _parse_obi(row: dict) -> dict:
    raw = row.get("obi_json")
    if not raw:
        return {}
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw)
    except (TypeError, json.JSONDecodeError):
        return {}


def _join_taken(candidates: list[dict], paper_trades: list[dict]) -> list[dict]:
    by_key: dict[tuple, dict] = {}
    for c in candidates:
        if not c.get("taken"):
            continue
        key = (c.get("ticker"), c.get("side"), round(float(c.get("ts") or 0), 1))
        by_key[key] = c
    out = []
    for t in paper_trades:
        if not t.get("settled"):
            continue
        key = (t.get("ticker"), t.get("side"), round(float(t.get("entry_ts") or 0), 1))
        c = by_key.get(key)
        obi = _parse_obi(c) if c else {}
        out.append({**t, **obi, "obi_agrees_side": obi.get("obi_agrees_side")})
    return out


BUCKETS = ["<0.35", "0.35-0.45", "0.45-0.55", "0.55-0.65", ">0.65"]


def obi_analytics(candidates: list[dict], paper_trades: list[dict]) -> dict:
    taken = _join_taken(candidates, paper_trades)
    bucket_rows: list[dict] = []
    for strat in sorted({r.get("strategy") or "unknown" for r in taken}):
        for asset in sorted({r.get("asset") or "?" for r in taken}):
            subset = [r for r in taken if (r.get("strategy") or "unknown") == strat and r.get("asset") == asset]
            for b in BUCKETS:
                rows = [r for r in subset if obi_bucket(r.get("obi_comb_top3")) == b]
                bucket_rows.append({"strategy": strat, "asset": asset, "bucket": b, **_stats(rows)})

    def agree_split(*, persistent_only: bool) -> list[dict]:
        rows_out: list[dict] = []
        for strat in sorted({r.get("strategy") or "unknown" for r in taken}):
            for asset in sorted({r.get("asset") or "?" for r in taken}):
                base = [r for r in taken if (r.get("strategy") or "unknown") == strat and r.get("asset") == asset]
                if persistent_only:
                    base = [r for r in base if r.get("obi_persistent")]
                for label in ("true", "false", "null"):
                    if label == "true":
                        rows = [r for r in base if r.get("obi_agrees_side") is True]
                    elif label == "false":
                        rows = [r for r in base if r.get("obi_agrees_side") is False]
                    else:
                        rows = [r for r in base if r.get("obi_agrees_side") is None]
                    rows_out.append(
                        {
                            "strategy": strat,
                            "asset": asset,
                            "agrees": label,
                            "persistent_only": persistent_only,
                            **_stats(rows),
                        }
                    )
        return rows_out

    agree_all = agree_split(persistent_only=False)
    agree_pers = agree_split(persistent_only=True)

    summary_lines: list[str] = []
    for strat in sorted({r.get("strategy") or "unknown" for r in taken}):
        for asset in sorted({r.get("asset") or "?" for r in taken}):
            t_rows = [r for r in agree_all if r["strategy"] == strat and r["asset"] == asset and r["agrees"] == "true"]
            f_rows = [r for r in agree_all if r["strategy"] == strat and r["asset"] == asset and r["agrees"] == "false"]
            if not t_rows or not f_rows:
                continue
            t, f = t_rows[0], f_rows[0]
            if t["count"] < 1 or f["count"] < 1:
                continue
            tw = t.get("win_rate")
            fw = f.get("win_rate")
            if tw is None or fw is None:
                continue
            delta = tw - fw
            pnl_d = (t.get("net_pnl") or 0) - (f.get("net_pnl") or 0)
            who = "true agrees" if delta >= 0 else "false agrees"
            summary_lines.append(
                f"{strat} · {asset}: {who} WR by {abs(delta)*100:.1f}pp · net P&L Δ ${pnl_d:.2f} (n true={t['count']}, false={f['count']})"
            )

    return {
        "obi_buckets": bucket_rows,
        "obi_agrees": agree_all,
        "obi_agrees_persistent": agree_pers,
        "obi_summary": summary_lines,
    }
