from desk.engine.view import fill_journal_rows_for_ui


def test_fill_journal_reads_exit_px_column():
    rows = [
        {
            "ts": 1.0,
            "asset": "BTC",
            "side": "YES",
            "entry": 0.45,
            "exit_px": 1.0,
            "contracts": 1,
            "net_pnl": 0.55,
            "right": 1,
            "mode": "paper-settled",
            "ticker": "T",
        }
    ]
    out = fill_journal_rows_for_ui(rows)
    assert len(out) == 1
    assert out[0]["exit_px"] == 1.0
    assert out[0]["outcome"] == "UP"
    assert out[0]["dir_ok"] is True
    assert out[0]["pending"] is False
