"""S3: late-window settlement lock (running average vs strike)."""
from __future__ import annotations

from desk.engine.modular_bot.context import BotContext
from desk.engine.modular_bot.types import StrategySignal


def _avg_60(samples: list[tuple[float, float]], now: float) -> float | None:
    window = [px for ts, px in samples if now - ts <= 60]
    if len(window) < 5:
        return None
    return sum(window) / len(window)


def evaluate_s3(ctx: BotContext, cfg: dict) -> StrategySignal | None:
    sc = cfg.get("strategies", {}).get("s3_settlement_lock") or {}
    if not sc.get("enabled", True):
        return None
    t_max = float(sc.get("secs_left_max", 360))
    if ctx.secs_left is None or ctx.secs_left > t_max:
        return None
    settle = (ctx.measurements or {}).get("settlement") or {}
    locked_frac = settle.get("locked_in_fraction")
    cushion_sig = settle.get("cushion_sigmas")
    if locked_frac is None:
        avg = ctx.composite_avg_60s or _avg_60(ctx.samples, ctx.ts)
        if avg is None or ctx.strike is None or ctx.sigma_t is None or ctx.sigma_t <= 0:
            return None
        cushion_sig = abs(avg - ctx.strike) / ctx.sigma_t
        locked_frac = min(1.0, max(0.0, (60 - (ctx.secs_left or 0)) / 60.0))
    min_frac = float(sc.get("min_locked_fraction", 0.55))
    min_cushion = float(sc.get("min_cushion_sigmas", 1.2))
    if locked_frac < min_frac or (cushion_sig or 0) < min_cushion:
        return None
    avg = ctx.composite_avg_60s or _avg_60(ctx.samples, ctx.ts)
    if avg is None or ctx.strike is None:
        return None
    side = "UP" if avg >= ctx.strike else "DOWN"
    return StrategySignal(
        strategy_id="s3_settlement_lock",
        side=side,
        detail=f"lock frac={locked_frac:.2f} cushion={cushion_sig:.2f}σ",
        meta={"locked_frac": locked_frac, "cushion_sigmas": cushion_sig},
    )
