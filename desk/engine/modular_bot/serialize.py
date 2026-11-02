"""JSON-serializable decision records."""
from __future__ import annotations

from dataclasses import asdict

from desk.engine.modular_bot.types import BotDecision


def decision_to_dict(d: BotDecision) -> dict:
    return asdict(d)
