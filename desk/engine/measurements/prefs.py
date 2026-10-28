"""Toggle which measurement packs are logged."""
from __future__ import annotations

MEASUREMENT_PREFS_KEY = "measurement_prefs"

DEFAULTS = {
    "settlement_window": True,
    "book_metrics": True,
    "window_features": True,
    "liquidation": False,
    "price_buckets": True,
}


def load_measurement_prefs(settings: dict) -> dict:
    raw = settings.get(MEASUREMENT_PREFS_KEY) or {}
    out = dict(DEFAULTS)
    for k in out:
        if k in raw:
            out[k] = bool(raw[k])
    return out
