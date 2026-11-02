from desk.engine.arbitrage_chart import build_arbitrage_chart_payload, mock_arbitrage_series, series_from_composite_points


def test_mock_series_has_rows():
    data = mock_arbitrage_series(timesteps=30)
    assert data["ok"]
    assert len(data["rows"]) == 30
    assert data["rows"][0]["strike"] == 65000.0


def test_live_series_from_points():
    pts = [{"t": 1000 + i, "c": 65000.0 + i * 0.5, "s": 65000.0} for i in range(20)]
    out = series_from_composite_points(pts, strike=65000.0)
    assert out["ok"]
    assert len(out["rows"]) == 20
    assert out["rows"][-1]["close"] == 65000.0 + 19 * 0.5


def test_live_series_includes_venue_lines():
    pts = [
        {
            "t": 1000 + i,
            "c": 65000.0 + i,
            "s": 65000.0,
            "venues": {"coinbase": 65000.0 + i, "kraken": 65000.0 + i - 1},
        }
        for i in range(5)
    ]
    out = series_from_composite_points(pts, strike=65000.0)
    assert out["ok"]
    assert set(out["venue_series"].keys()) == {"coinbase", "kraken"}
    assert len(out["venue_series"]["coinbase"]) == 5


def test_live_series_dedupes_same_second_timestamps():
    pts = [{"t": 1000.1, "c": 65000.0, "s": 65000.0}, {"t": 1000.8, "c": 65001.0, "s": 65000.0}]
    out = series_from_composite_points(pts, strike=65000.0)
    times = [r["time"] for r in out["rows"]]
    assert times == sorted(times)
    assert len(times) == len(set(times))


def test_strike_from_point_when_book_strike_missing():
    pts = [{"t": 1000, "c": 65000.0, "s": 65100.0}]
    out = series_from_composite_points(pts, strike=None)
    assert out["ok"]
    assert out["rows"][0]["strike"] == 65100.0


def test_payload_live_only_even_with_few_points():
    pts = [{"t": 1000, "c": 65000.0, "s": 65000.0}]
    p = build_arbitrage_chart_payload(asset="BTC", chart_points=pts, strike=65000.0)
    assert p["source"] == "live"
    assert p["ok"]
    assert len(p["rows"]) == 1


def test_payload_no_demo_when_empty():
    p = build_arbitrage_chart_payload(asset="BTC", chart_points=[], strike=65000.0)
    assert not p["ok"]
    assert p["rows"] == []
    assert "Waiting" in (p.get("note") or "")
