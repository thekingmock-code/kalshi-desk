"""Account and paper balance summaries for the dashboard header."""
from __future__ import annotations


def parse_kalshi_balance(body: dict) -> dict:
    bal = body.get("balance_dollars")
    if bal is not None and bal != "":
        available = float(bal)
    else:
        cents = body.get("balance")
        available = None if cents is None else float(cents) / 100.0
    pv = body.get("portfolio_value_dollars")
    if pv is None and body.get("portfolio_value") is not None:
        pv = float(body["portfolio_value"]) / 100.0
    elif pv is not None and pv != "":
        pv = float(pv)
    else:
        pv = None
    return {"available": available, "portfolio_value": pv}


def paper_summary(
    *,
    starting_balance: float,
    journal_rows: list[dict],
    open_mark_pnls: list[float],
) -> dict:
    realized = 0.0
    for row in journal_rows:
        mode = row.get("mode") or ""
        if "paper" not in mode:
            continue
        pnl = row.get("net_pnl")
        if pnl is not None:
            realized += float(pnl)
    unrealized = sum(open_mark_pnls)
    total_pnl = realized + unrealized
    equity = starting_balance + total_pnl
    return {
        "starting_balance": starting_balance,
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_pnl": total_pnl,
        "equity": equity,
    }
