from desk.engine.gauge import build_gauge


def test_gauge_no_data():
    g = build_gauge(composite=None, strike=100.0, move_1m=1.0, baseline_move=1.0, secs_left=300.0, favored="UP")
    assert g["ok"] is False


def test_gauge_sigma():
    g = build_gauge(composite=101.0, strike=100.0, move_1m=10.0, baseline_move=10.0, secs_left=300.0, favored="UP")
    assert g["ok"] is True
    assert g["gap_usd"] == 1.0
    assert g["sigma"] is not None
