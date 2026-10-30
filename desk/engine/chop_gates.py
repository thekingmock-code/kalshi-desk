"""Chop log settings (paper). Soft/hard tiers kept for defaults reset only — no entry impact."""
from __future__ import annotations

CHOP_GATES_KEY = "chop_gates"

DEFAULTS = {
    "log_threshold": 30.0,
    "log_basis": "original",
    "show_log_row": True,
    "soft_enabled": False,
    "tier_low_max": 30.0,
    "tier_mid_max": 50.0,
    "addon_below_low_cents": 2.0,
    "addon_mid_cents": 1.0,
    "hard_enabled": False,
    "chop_hard_min": 0.0,
}


def load_chop_gates(settings: dict) -> dict:
    raw = settings.get(CHOP_GATES_KEY) or {}
    out = dict(DEFAULTS)
    for k in out:
        if k in raw:
            out[k] = raw[k]
    out["show_log_row"] = bool(out["show_log_row"])
    out["soft_enabled"] = bool(out["soft_enabled"])
    out["hard_enabled"] = bool(out["hard_enabled"])
    out["log_threshold"] = max(0.0, min(100.0, float(out["log_threshold"])))
    basis = str(out.get("log_basis", "original")).lower()
    out["log_basis"] = basis if basis in ("original", "adjusted") else "original"
    out["tier_low_max"] = max(0.0, min(100.0, float(out["tier_low_max"])))
    out["tier_mid_max"] = max(out["tier_low_max"], min(100.0, float(out["tier_mid_max"])))
    out["chop_hard_min"] = max(0.0, min(60.0, float(out["chop_hard_min"])))
    return out


def reset_chop_soft_defaults() -> dict:
    return {
        "tier_low_max": DEFAULTS["tier_low_max"],
        "tier_mid_max": DEFAULTS["tier_mid_max"],
        "addon_below_low_cents": DEFAULTS["addon_below_low_cents"],
        "addon_mid_cents": DEFAULTS["addon_mid_cents"],
    }
