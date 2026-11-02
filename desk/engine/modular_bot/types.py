"""Shared types for the modular 15m bot (paper / dry-run by default)."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class StrategySignal:
    strategy_id: str
    side: str  # UP or DOWN
    detail: str = ""
    meta: dict[str, Any] = field(default_factory=dict)


@dataclass
class HardGateResult:
    ok: bool
    first_block: str | None = None
    checks: list[dict[str, Any]] = field(default_factory=list)


@dataclass
class BotDecision:
    ts: float
    asset: str
    ticker: str | None
    secs_left: float | None
    composite: float | None
    composite_avg_60s: float | None
    fair_up: float | None
    yes_bid: float | None
    yes_ask: float | None
    no_bid: float | None
    no_ask: float | None
    depth_hint: str | None
    quote_age_s: float | None
    strategies_fired: list[str]
    proposed_side: str | None
    contributing: list[str]
    hard_gate_ok: bool
    first_blocking_gate: str | None
    soft_penalty_cents: float
    would_trade: bool
    dry_run: bool
    skip_reason: str | None
    latency_ms: dict[str, float | None]
    venue_ages: dict[str, float]
    extra: dict[str, Any] = field(default_factory=dict)
