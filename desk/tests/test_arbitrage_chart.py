from desk.engine.arbitrage_chart import build_arbitrage_chart_payload, mock_arbitrage_series, series_from_composite_points


def test_mock_series_has_rows():
    data = mock_arbitrage_series(timesteps=30)
    assert data["ok"]
    assert len(data["rows"]) == 30
    assert data["rows"][0]["strike"] == 65000.0


def test_live_series_from_points():
    pts = [{"t": 1000 + i, "c": 65000.0 + i * 0.5} for i in range(20)]
    out = series_from_composite_points(pts, strike=65000.0)
    assert out["ok"]
    assert len(out["rows"]) == 20
    assert out["rows"][-1]["close"] == 65000.0 + 19 * 0.5


def test_payload_prefers_live_when_enough_points():
    pts = [{"t": 1000 + i, "c": 65000.0 + i} for i in range(20)]
    p = build_arbitrage_chart_payload(asset="BTC", chart_points=pts, strike=65000.0, min_live_points=15)
    assert p["source"] == "live"
    assert p["asset"] == "BTC"
