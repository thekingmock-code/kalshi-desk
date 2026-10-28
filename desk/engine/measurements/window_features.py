"""Per-15m-window chop / fakeout features (log-only)."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class WindowFeatureState:
    ticker: str | None = None
    strike_crosses: int = 0
    max_excursion_up: float = 0.0
    max_excursion_down: float = 0.0
    src_disagree_max: float = 0.0
    spike_revert_60s: bool = False
    _last_sign: int | None = None
    _spike_dir: int | None = None
    _spike_extreme: float | None = None
    _spike_ts: float | None = None

    def reset(self, ticker: str | None) -> None:
        self.ticker = ticker
        self.strike_crosses = 0
        self.max_excursion_up = 0.0
        self.max_excursion_down = 0.0
        self.src_disagree_max = 0.0
        self.spike_revert_60s = False
        self._last_sign = None
        self._spike_dir = None
        self._spike_extreme = None
        self._spike_ts = None

    def tick(
        self,
        *,
        now: float,
        composite: float | None,
        strike: float | None,
        move_1m: float | None,
        coinbase: float | None,
        kraken: float | None,
    ) -> dict:
        if composite is not None and strike is not None:
            diff = composite - strike
            self.max_excursion_up = max(self.max_excursion_up, diff)
            self.max_excursion_down = min(self.max_excursion_down, diff)
            sign = 1 if diff > 0 else (-1 if diff < 0 else 0)
            if sign != 0 and self._last_sign is not None and sign != self._last_sign:
                self.strike_crosses += 1
            if sign != 0:
                self._last_sign = sign
        if coinbase is not None and kraken is not None:
            self.src_disagree_max = max(self.src_disagree_max, abs(coinbase - kraken))
        thresh = 2.0 * (move_1m or 0.0)
        if composite is not None and strike is not None and move_1m and move_1m > 0:
            move_from_strike = composite - strike
            if abs(move_from_strike) >= thresh:
                direction = 1 if move_from_strike > 0 else -1
                if self._spike_dir != direction:
                    self._spike_dir = direction
                    self._spike_extreme = composite
                    self._spike_ts = now
                elif self._spike_extreme is not None:
                    if direction > 0:
                        self._spike_extreme = max(self._spike_extreme, composite)
                    else:
                        self._spike_extreme = min(self._spike_extreme, composite)
                    span = abs(self._spike_extreme - strike)
                    if span >= thresh and self._spike_ts and now - self._spike_ts <= 60:
                        retrace = abs(composite - self._spike_extreme)
                        if retrace >= 0.6 * span:
                            self.spike_revert_60s = True
        return {
            "strike_crosses": self.strike_crosses,
            "max_excursion_up": self.max_excursion_up,
            "max_excursion_down": self.max_excursion_down,
            "spike_revert_60s": int(self.spike_revert_60s),
            "src_disagree_usd": self.src_disagree_max,
        }
