"""Hard-coded gate rules (not slider-controlled)."""
from __future__ import annotations

ENTRY_SECS_MAX = 720.0  # no entry until 3m warmup elapsed (~720s left)
ENTRY_SECS_MIN = 120.0  # last 2m blocked
COMPOSITE_MAX_AGE = 2.0
MID_DIVERGENCE_VETO = 0.10
LATE_SECS = 300.0
LATE_EDGE_EXTRA = 0.02
ARB_WINDOW_MIN = 120.0
ARB_WINDOW_MAX = 660.0
ARB_STALE_COMPOSITE_PCT = 0.0002  # 0.02%
ARB_STALE_LOOKBACK = 3.0
ARB_PAD_BASE = 0.03
ARB_PAD_VOL = 0.02
ARB_VOL_HOT = 1.5
ARB_EXIT_CAP = 0.82
SOL_NET_EDGE_MIN = 0.03
SOL_ASK_MIN = 0.35
SOL_ASK_MAX = 0.55
SOL_CONFIRM_SECS = 3.0
SUB25_ASK_MAX = 0.25
SUB25_EDGE_MIN = 0.05
SUB25_BLACKOUT = 120.0

LOCKED_LABELS = [
    "Entry window (720s–120s left)",
    "Composite feeds (CB+KR <2s)",
    "Model vs mid divergence",
    "Late-window edge (+2¢ under 300s)",
]
