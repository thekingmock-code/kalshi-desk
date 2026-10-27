"""Per-asset tunable params with server-side clamps."""
from __future__ import annotations

from copy import deepcopy
from typing import Any

ASSETS = ("BTC", "SOL", "BNB")

# default, min, max per asset
_SCHEMA: dict[str, dict[str, dict[str, tuple[float, float, float]]]] = {
    "net_edge_min": {
        "BTC": (0.02, 0.02, 0.06),
        "SOL": (0.03, 0.02, 0.06),
        "BNB": (0.03, 0.02, 0.06),
    },
    "ask_floor": {
        "BTC": (0.35, 0.25, 0.45),
        "SOL": (0.35, 0.25, 0.45),
        "BNB": (0.38, 0.25, 0.45),
    },
    "ask_cap": {
        "BTC": (0.65, 0.50, 0.70),
        "SOL": (0.55, 0.50, 0.70),
        "BNB": (0.58, 0.50, 0.70),
    },
    "spread_max": {
        "BTC": (0.03, 0.02, 0.05),
        "SOL": (0.04, 0.02, 0.05),
        "BNB": (0.04, 0.02, 0.05),
    },
    "flow_min": {
        "BTC": (0.58, 0.52, 0.65),
        "SOL": (0.58, 0.52, 0.65),
        "BNB": (0.55, 0.52, 0.65),
    },
    "vol_max": {
        "BTC": (2.0, 1.5, 2.5),
        "SOL": (2.0, 1.5, 2.5),
        "BNB": (1.8, 1.5, 2.5),
    },
    "vol_min": {
        "BTC": (0.5, 0.3, 0.8),
        "SOL": (0.5, 0.3, 0.8),
        "BNB": (0.5, 0.3, 0.8),
    },
    "trend_sigma_min": {
        "BTC": (0.5, 0.3, 1.0),
        "SOL": (0.5, 0.3, 1.0),
        "BNB": (0.5, 0.3, 1.0),
    },
}

GATES_15M_KEYS = (
    "net_edge_min",
    "ask_floor",
    "ask_cap",
    "spread_max",
    "flow_min",
    "vol_max",
    "vol_min",
    "trend_sigma_min",
)

ARB_KEYS = ("ask_floor", "ask_cap", "spread_max", "vol_max")

WEEKEND_KEYS = (
    "trend_sigma_min",
    "prob_edge_min_cents",
    "weekend_bump_cents",
    "ask_floor",
    "ask_cap",
    "spread_max",
    "entry_hold_secs",
)

WEEKEND_DEFAULTS: dict[str, dict[str, float]] = {
    "BTC": {
        "trend_sigma_min": 0.30,
        "prob_edge_min_cents": 3.0,
        "ask_floor": 0.38,
        "ask_cap": 0.55,
        "spread_max": 0.03,
        "entry_hold_secs": 2.0,
        "weekend_bump_cents": 0.0,
    },
    "SOL": {
        "trend_sigma_min": 0.30,
        "prob_edge_min_cents": 3.0,
        "ask_floor": 0.38,
        "ask_cap": 0.55,
        "spread_max": 0.03,
        "entry_hold_secs": 2.0,
        "weekend_bump_cents": 0.0,
    },
    "BNB": {
        "trend_sigma_min": 0.32,
        "prob_edge_min_cents": 3.0,
        "ask_floor": 0.40,
        "ask_cap": 0.55,
        "spread_max": 0.05,
        "entry_hold_secs": 2.0,
        "weekend_bump_cents": 0.0,
    },
}

SLIDER_META: dict[str, dict[str, Any]] = {
    "net_edge_min": {"label": "Net edge min", "step": 0.005, "unit": "dollars"},
    "ask_floor": {"label": "Ask floor", "step": 0.01, "unit": "cents"},
    "ask_cap": {"label": "Ask cap", "step": 0.01, "unit": "cents"},
    "spread_max": {"label": "Spread max", "step": 0.005, "unit": "dollars"},
    "flow_min": {"label": "Taker flow min", "step": 0.01, "unit": "percent"},
    "vol_max": {"label": "Vol max vs baseline", "step": 0.1, "unit": "ratio"},
    "vol_min": {"label": "Vol min vs baseline", "step": 0.05, "unit": "ratio"},
    "trend_sigma_min": {"label": "Trend σ min", "step": 0.05, "unit": "ratio"},
    "prob_edge_min_cents": {"label": "Prob edge min", "step": 0.5, "unit": "cents_raw"},
    "weekend_bump_cents": {"label": "Weekend G4 bump (c)", "step": 0.5, "unit": "cents_raw"},
    "entry_hold_secs": {"label": "Signal hold", "step": 1, "unit": "seconds"},
}


def default_params(asset: str, keys: tuple[str, ...]) -> dict[str, float]:
    out: dict[str, float] = {}
    for key in keys:
        row = _SCHEMA[key][asset]
        out[key] = row[0]
    return out


def clamp_param(asset: str, key: str, value: float) -> float:
    if key not in _SCHEMA or asset not in _SCHEMA[key]:
        raise KeyError(key)
    _default, lo, hi = _SCHEMA[key][asset]
    return min(hi, max(lo, float(value)))


def slider_defs(strategy_id: str, asset: str) -> list[dict]:
    if strategy_id == "gates_15m":
        keys = GATES_15M_KEYS
    elif strategy_id == "spot_arb":
        keys = ARB_KEYS
    elif strategy_id == "sol_15m":
        keys = ("net_edge_min", "spread_max", "vol_max")
    elif strategy_id == "weekend_money":
        keys = WEEKEND_KEYS
    else:
        return []
    sliders = []
    for key in keys:
        meta = SLIDER_META[key]
        if key in _SCHEMA:
            _default, lo, hi = _SCHEMA[key][asset]
        elif strategy_id == "weekend_money" and key == "prob_edge_min_cents":
            lo, hi = 2.0, 8.0
        elif strategy_id == "weekend_money" and key == "entry_hold_secs":
            lo, hi = 2.0, 15.0
        elif strategy_id == "weekend_money" and key == "weekend_bump_cents":
            lo, hi = 0.0, 5.0
        else:
            continue
        sliders.append(
            {
                "key": key,
                "label": meta["label"],
                "min": lo,
                "max": hi,
                "step": meta["step"],
                "unit": meta["unit"],
            }
        )
    return sliders


def merge_params(strategy_id: str, asset: str, saved: dict | None) -> dict[str, float]:
    if strategy_id == "gates_15m":
        keys = GATES_15M_KEYS
    elif strategy_id == "spot_arb":
        keys = ARB_KEYS
    elif strategy_id == "sol_15m":
        keys = ("net_edge_min", "spread_max", "vol_max")
    elif strategy_id == "weekend_money":
        base = dict(WEEKEND_DEFAULTS.get(asset, WEEKEND_DEFAULTS["BTC"]))
        if saved:
            for k, v in saved.items():
                if k in base:
                    try:
                        if k in _SCHEMA:
                            base[k] = clamp_param(asset, k, float(v))
                        elif k == "weekend_bump_cents":
                            base[k] = max(0.0, min(5.0, float(v)))
                        else:
                            base[k] = float(v)
                    except (KeyError, TypeError, ValueError):
                        pass
        return base
    else:
        return {}
    base = default_params(asset, keys)
    if saved:
        for k, v in saved.items():
            if k in base:
                try:
                    base[k] = clamp_param(asset, k, float(v))
                except (KeyError, TypeError, ValueError):
                    pass
    return base


def settings_key(strategy_id: str, asset: str) -> str:
    return f"params:{strategy_id}:{asset}"


def pending_key(strategy_id: str, asset: str) -> str:
    return f"pending:{strategy_id}:{asset}"


def all_defaults_for_reset() -> dict[str, dict[str, float]]:
    """Flat map strategy:asset -> params for reset."""
    out: dict[str, dict[str, float]] = {}
    for sid, keys in (
        ("gates_15m", GATES_15M_KEYS),
        ("spot_arb", ARB_KEYS),
        ("sol_15m", ("net_edge_min", "spread_max", "vol_max")),
        ("weekend_money", WEEKEND_KEYS),
    ):
        if sid == "weekend_money":
            for asset in ASSETS:
                out[f"{sid}:{asset}"] = dict(WEEKEND_DEFAULTS.get(asset, WEEKEND_DEFAULTS["BTC"]))
            continue
        for asset in ASSETS:
            out[f"{sid}:{asset}"] = default_params(asset, keys)
    return out
