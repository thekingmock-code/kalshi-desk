from desk.engine.obi_analytics import obi_analytics
from desk.engine.spot_obi import (
    ObiPersistence,
    VenueBook,
    build_obi_snapshot,
    obi_agrees_side,
    obi_bucket,
    venue_metrics,
)


def test_venue_top3_and_50bps():
    book = VenueBook()
    book.apply_snapshot(
        [(100.0, 2.0), (99.0, 1.0), (98.0, 1.0)],
        [(101.0, 1.0), (102.0, 1.0), (103.0, 1.0)],
        1.0,
    )
    m = venue_metrics(book, 100.5)
    assert m["bid_depth_top3"] == 4.0
    assert m["ask_depth_top3"] == 3.0
    assert abs(m["obi_top3"] - 4.0 / 7.0) < 0.001


def test_persistence_and_agrees():
    p = ObiPersistence(window_s=10.0)
    cb = VenueBook()
    cb.apply_snapshot([(100.0, 3.0)], [(101.0, 1.0)], 0.0)
    snap = build_obi_snapshot(
        coinbase_book=cb,
        kraken_book=None,
        coinbase_mid=100.0,
        kraken_mid=None,
        persistence=p,
        ts=1.0,
        entry_side="UP",
    )
    assert snap["obi_comb_top3"] is not None
    assert snap["obi_agrees_side"] is True
    assert obi_agrees_side(0.4, "DOWN") is True
    assert obi_agrees_side(0.5, "UP") is None
    assert obi_bucket(0.72) == ">0.65"


def test_obi_analytics_buckets():
    candidates = [
        {
            "taken": True,
            "ticker": "T",
            "side": "YES",
            "ts": 100.0,
            "obi_json": {
                "obi_comb_top3": 0.6,
                "obi_agrees_side": True,
                "obi_persistent": True,
            },
        }
    ]
    trades = [
        {
            "settled": True,
            "ticker": "T",
            "side": "YES",
            "entry_ts": 100.0,
            "strategy": "gates_15m",
            "asset": "BTC",
            "net_pnl": 1.0,
            "right": True,
        }
    ]
    rep = obi_analytics(candidates, trades)
    assert any(r["bucket"] == "0.55-0.65" and r["count"] == 1 for r in rep["obi_buckets"])
