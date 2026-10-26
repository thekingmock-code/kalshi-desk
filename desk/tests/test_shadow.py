from desk.engine.shadow import settle_shadow_row


def test_settle_yes_wins_when_up():
    row = {"side": "YES", "entry_ask": 0.45, "strike": 100.0}
    out = settle_shadow_row(row, 101.0, 100.0, 0.07)
    assert out["right"] == 1
    assert out["up_won"] == 1
    assert out["exit_px"] == 1.0
    assert out["net_pnl"] is not None


def test_settle_no_wins_when_down():
    row = {"side": "NO", "entry_ask": 0.40, "strike": 100.0}
    out = settle_shadow_row(row, 99.0, 100.0, 0.07)
    assert out["right"] == 1
    assert out["up_won"] == 0


def test_settle_direction_wrong():
    row = {"side": "YES", "entry_ask": 0.50, "strike": 100.0}
    out = settle_shadow_row(row, 99.0, 100.0, 0.07)
    assert out["right"] == 0
    assert out["up_won"] == 0


def test_settle_uses_row_strike_when_book_missing():
    row = {"side": "YES", "entry_ask": 0.50, "strike": 200.0}
    out = settle_shadow_row(row, 201.0, None, 0.07)
    assert out["right"] == 1


def test_settle_skips_without_price():
    row = {"side": "YES", "entry_ask": 0.50, "strike": 100.0}
    out = settle_shadow_row(row, None, 100.0, 0.07)
    assert out.get("settled", 0) == 0
    assert "right" not in out or out.get("right") is None
