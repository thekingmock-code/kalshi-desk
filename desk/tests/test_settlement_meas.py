from desk.engine.measurements.analytics import ask_price_bucket
from desk.engine.measurements.settlement import locked_frac, p_up_avgmodel, window_avg_so_far


def test_window_avg_before_t_minus_60_is_null():
    close = 1000.0
    assert window_avg_so_far([], close, 920.0, 100.0) is None
    assert locked_frac(close, 920.0) is None


def test_locked_frac_mid_window():
    close = 1000.0
    assert abs(locked_frac(close, 970.0) - 0.5) < 1e-6


def test_p_up_avgmodel_high_when_avg_above_strike():
    p = p_up_avgmodel(ref=101.0, strike=100.0, move_1m=10.0, window_avg=100.5, locked=0.5)
    assert p is not None and p > 0.5


def test_ask_buckets():
    assert ask_price_bucket(0.08) == "<10c"
    assert ask_price_bucket(0.42) == "40-55c"
