"""Tick context assembled from desk runtime (read-only snapshot)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class BotContext:
    ts: float
    asset: str
    ticker: str | None
    secs_left: float | None
    strike: float | None
    composite: float | None
    composite_avg_60s: float | None
    samples: list[tuple[float, float]]
    move_1m: float | None
    move_5m: float | None
    move_1h: float | None
    p_up: float | None
    sigma_t: float | None
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
    yes_mid: float | None
    no_mid: float | None
    mid_history: list[tuple[float, float]]  # (ts, yes_mid)
    kalshi_mid_move_3s: float | None
    composite_pct_move_3s: float | None
    momentum: int | None
    buy_pct: float | None
    vol_ratio: float | None
    btc_momentum: int | None
    feed_ages: dict[str, float]
    already_entered_market: bool
    has_open_position: bool
    open_side: str | None  # UP/DOWN or None
    taker_rate: float
    model_cfg: dict
    fees_cfg: dict
    measurements: dict[str, Any] = field(default_factory=dict)
    risk_state: dict[str, Any] = field(default_factory=dict)
