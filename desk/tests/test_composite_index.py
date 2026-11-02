import time

from desk.engine.composite_index import compute_composite
from desk.engine.model import composite_price
from desk.feeds.venues.base import VenueAssetState, utc_ms


def _state(mid: float, age_sec: float = 0.0, depth: float = 10.0) -> VenueAssetState:
    st = VenueAssetState()
    now_ms = utc_ms()
    st.mid = mid
    st.last_tick_ts_ms = now_ms - age_sec * 1000.0
    st.record_depth(depth, now_ms=now_ms)
    return st


def test_equal_weight_fallback_when_no_depth_history():
    cfg = {"drop_stale_venues": False}
    states = {"a": _state(100.0, depth=0), "b": _state(200.0, depth=0)}
    price, names, _ = compute_composite(states, composite_cfg=cfg)
    assert names == ["a", "b"]
    assert price == 150.0


def test_depth_weighting():
    cfg = {"drop_stale_venues": False}
    states = {"a": _state(100.0, depth=10.0), "b": _state(200.0, depth=30.0)}
    price, names, diag = compute_composite(states, composite_cfg=cfg)
    assert set(names) == {"a", "b"}
    assert price == 100.0 * 0.25 + 200.0 * 0.75
    assert diag["weights"]["b"] > diag["weights"]["a"]


def test_drop_stale_off_keeps_old_tick():
    now = time.time()
    cfg = {"drop_stale_venues": False, "stale_ms": 5000}
    st = VenueAssetState()
    st.mid = 100.0
    st.last_tick_ts_ms = (now - 20.0) * 1000.0
    price, names, _ = compute_composite({"x": st}, now=now, composite_cfg=cfg, legacy_stale_secs=5.0)
    assert price == 100.0
    assert names == ["x"]


def test_drop_stale_on_excludes():
    now = time.time()
    cfg = {"drop_stale_venues": True, "stale_ms": 5000}
    st = VenueAssetState()
    st.mid = 100.0
    st.last_tick_ts_ms = (now - 10.0) * 1000.0
    price, names, _ = compute_composite({"x": st}, now=now, composite_cfg=cfg)
    assert price is None
    assert names == []


def test_single_venue_fallback():
    cfg = {"drop_stale_venues": False}
    states = {"only": _state(42.0)}
    price, names, _ = compute_composite(states, composite_cfg=cfg)
    assert price == 42.0
    assert names == ["only"]


def test_legacy_composite_price_signature():
    now = 1000.0
    price, names = composite_price([("coinbase", 100.0, now), ("kraken", 200.0, now)], now, 5.0)
    assert price == 150.0
    assert len(names) == 2
