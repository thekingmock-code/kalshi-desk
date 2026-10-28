"""Build one measurement dict per tick."""
from __future__ import annotations

from desk.engine.measurements.book_tracker import BookMetricsState
from desk.engine.measurements.liquidation import LiquidationState
from desk.engine.measurements.prefs import load_measurement_prefs
from desk.engine.measurements.settlement import settlement_snapshot
from desk.engine.measurements.window_features import WindowFeatureState


def build_measurements(
    *,
    prefs: dict,
    samples: list[tuple[float, float]],
    close_ts: float | None,
    now: float,
    ref: float | None,
    strike: float | None,
    move_1m: float | None,
    p_up: float | None,
    book: dict,
    book_state: BookMetricsState,
    window_state: WindowFeatureState,
    liq_state: LiquidationState,
    composite: float | None,
    coinbase: float | None,
    kraken: float | None,
) -> dict:
    out: dict = {}
    if prefs.get("settlement_window"):
        out["settlement"] = settlement_snapshot(
            samples=samples,
            close_ts=close_ts,
            now=now,
            ref=ref,
            strike=strike,
            move_1m=move_1m,
            p_up=p_up,
        )
    if prefs.get("book_metrics"):
        out["book"] = book_state.snapshot(now, book)
    if prefs.get("window_features"):
        out["window"] = window_state.tick(
            now=now,
            composite=composite,
            strike=strike,
            move_1m=move_1m,
            coinbase=coinbase,
            kraken=kraken,
        )
    if prefs.get("liquidation"):
        out["liquidation"] = liq_state.snapshot(now)
    else:
        out["liquidation"] = {"liq_long_60s": None, "liq_short_60s": None, "liq_burst": None}
    return out
