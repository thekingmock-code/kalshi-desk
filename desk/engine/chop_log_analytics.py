"""Reporting for chop log-only gate vs taken paper trades."""
from __future__ import annotations


def _agg(rows: list[dict]) -> dict:
    settled = [r for r in rows if r.get("net_pnl") is not None and r.get("right") is not None]
    if not settled:
        return {"count": len(rows), "n_settled": 0, "win_rate": None, "net_pnl": 0.0}
    wins = sum(1 for r in settled if r.get("right"))
    pnl = sum(float(r["net_pnl"]) for r in settled)
    return {
        "count": len(rows),
        "n_settled": len(settled),
        "win_rate": wins / len(settled),
        "net_pnl": round(pnl, 4),
        "low_n": len(settled) < 30,
    }


def _join_taken(candidates: list[dict], paper_trades: list[dict]) -> list[dict]:
    taken_c = [c for c in candidates if c.get("taken")]
    by_key = {(c.get("ticker"), c.get("side"), c.get("strategy")): c for c in taken_c}
    out = []
    for t in paper_trades:
        if not t.get("settled"):
            continue
        c = by_key.get((t.get("ticker"), t.get("side"), t.get("strategy")))
        if not c:
            continue
        out.append({**t, **{k: c.get(k) for k in (
            "chop_log_would_block",
            "chop_log_secs_left_bucket",
            "chop_log_score",
            "asset",
        )}, "strategy": t.get("strategy") or c.get("strategy")})
    return out


def chop_log_analytics(candidates: list[dict], paper_trades: list[dict]) -> dict:
    taken = _join_taken(candidates, paper_trades)
    would = [r for r in taken if r.get("chop_log_would_block")]
    ok = [r for r in taken if not r.get("chop_log_would_block")]

    pnl_would = sum(float(r.get("net_pnl") or 0) for r in would)
    pnl_ok = sum(float(r.get("net_pnl") or 0) for r in ok)
    pnl_all = pnl_would + pnl_ok
    pnl_without = pnl_ok

    wr_w = _agg(would)
    wr_o = _agg(ok)
    underperform = None
    if wr_w["win_rate"] is not None and wr_o["win_rate"] is not None:
        underperform = wr_w["win_rate"] < wr_o["win_rate"]
    elif pnl_would != 0 or pnl_ok != 0:
        underperform = pnl_would < pnl_ok

    def split_dim(key: str) -> dict:
        out: dict[str, dict] = {}
        for flag, label in ((True, "would_block"), (False, "ok")):
            subset = [r for r in taken if bool(r.get("chop_log_would_block")) is flag]
            inner: dict[str, dict] = {}
            for r in subset:
                dim = str(r.get(key) or "unknown")
                inner.setdefault(dim, []).append(r)
            out[label] = {k: _agg(v) for k, v in inner.items()}
        return out

    by_strategy = split_dim("strategy")
    by_asset = split_dim("asset")
    by_bucket = split_dim("chop_log_secs_left_bucket")

    return {
        "taken_joined": len(taken),
        "would_block": wr_w,
        "would_pass": wr_o,
        "pnl_if_blocked_would_trades": round(pnl_would, 4),
        "pnl_without_would_block_trades": round(pnl_without, 4),
        "pnl_all_taken": round(pnl_all, 4),
        "would_block_underperform": underperform,
        "pnl_gap_would_minus_ok": round(pnl_would - pnl_ok, 4),
        "by_strategy": by_strategy,
        "by_asset": by_asset,
        "by_secs_bucket": by_bucket,
    }
