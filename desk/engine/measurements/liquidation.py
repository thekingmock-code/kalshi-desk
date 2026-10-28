"""Optional liquidation burst feed (log-only, null when unwired)."""
from __future__ import annotations

from dataclasses import dataclass, field
from collections import deque


@dataclass
class LiquidationState:
    enabled: bool = False
    events: deque = field(default_factory=lambda: deque(maxlen=5000))

    def note(self, ts: float, *, long_usd: float = 0.0, short_usd: float = 0.0) -> None:
        if self.enabled:
            self.events.append((ts, long_usd, short_usd))

    def snapshot(self, now: float) -> dict:
        if not self.enabled:
            return {"liq_long_60s": None, "liq_short_60s": None, "liq_burst": None}
        long_60 = short_60 = 0.0
        hist_long: list[float] = []
        hist_short: list[float] = []
        for ts, lng, sh in self.events:
            if now - ts <= 60:
                long_60 += lng
                short_60 += sh
            if now - ts <= 86400:
                hist_long.append(lng)
                hist_short.append(sh)
        burst = False
        if hist_long:
            p95_l = sorted(hist_long)[int(0.95 * (len(hist_long) - 1))]
            p95_s = sorted(hist_short)[int(0.95 * (len(hist_short) - 1))] if hist_short else 0
            burst = long_60 >= p95_l or short_60 >= p95_s
        return {
            "liq_long_60s": long_60 or None,
            "liq_short_60s": short_60 or None,
            "liq_burst": int(burst),
        }
