"""ET hour and session labels for paper trade logging."""
from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


def session_from_et(hour: int, minute: int) -> str:
    """US / Asia / Overnight buckets in Eastern time."""
    mins = hour * 60 + minute
    # US regular hours ~ 9:30–16:00 ET
    if 570 <= mins < 960:
        return "US"
    # Asia evening through early ET morning
    if mins >= 1080 or mins < 180:
        return "Asia"
    return "Overnight"


def entry_log_meta(ts: float, *, tz: str = "America/New_York") -> tuple[int, str]:
    zone = ZoneInfo(tz if tz in ("America/New_York", "UTC") else "America/New_York")
    dt = datetime.fromtimestamp(ts, zone)
    return dt.hour, session_from_et(dt.hour, dt.minute)
