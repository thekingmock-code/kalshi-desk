from desk.engine.balances import paper_summary, parse_kalshi_balance


def test_parse_kalshi_balance_dollars():
    out = parse_kalshi_balance({"balance_dollars": "123.4500", "portfolio_value": 15000})
    assert out["available"] == 123.45
    assert out["portfolio_value"] == 150.0


def test_paper_summary():
    rows = [{"mode": "paper-settled", "net_pnl": 5.0}, {"mode": "closed", "net_pnl": 99.0}]
    out = paper_summary(starting_balance=1000.0, journal_rows=rows, open_mark_pnls=[2.5])
    assert out["realized_pnl"] == 5.0
    assert out["total_pnl"] == 7.5
    assert out["equity"] == 1007.5
