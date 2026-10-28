from datetime import datetime
from zoneinfo import ZoneInfo

from desk.engine.trade_log_meta import entry_log_meta, session_from_et


def test_session_us_midday():
    assert session_from_et(12, 0) == "US"


def test_session_asia_evening():
    assert session_from_et(20, 0) == "Asia"


def test_entry_log_meta_returns_hour():
    # 2024-01-15 14:30 UTC = 09:30 ET (US session)
    ts = datetime(2024, 1, 15, 14, 30, tzinfo=ZoneInfo("UTC")).timestamp()
    hour, session = entry_log_meta(ts)
    assert hour == 9
    assert session == "US"
