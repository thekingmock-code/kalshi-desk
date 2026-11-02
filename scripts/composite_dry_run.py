#!/usr/bin/env python3
"""Print live composite + per-venue deviation for 60 seconds."""
from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from desk.engine.composite_index import compute_composite, log_trade_deviations
from desk.engine.load import load_config
from desk.feeds.venues.registry import build_venue_states, start_venue_tasks


async def main() -> None:
    cfg = load_config()
    assets = cfg["assets"]
    asset = sys.argv[1] if len(sys.argv) > 1 else "BTC"
    if asset not in assets:
        print(f"Unknown asset {asset}; choose from {list(assets)}")
        sys.exit(1)
    states = build_venue_states(cfg, assets)
    stop = asyncio.Event()
    comp_cfg = cfg.get("composite") or {}

    def on_trade(venue: str, a: str, usd: float, is_buy: bool, ts: float) -> None:
        del usd, is_buy, ts
        if a != asset:
            return
        price, names, diag = compute_composite(states[asset], composite_cfg=comp_cfg, now=time.time())
        log_trade_deviations(asset, price, diag, trigger_venue=venue)
        print(f"[trade {venue}] composite={price} venues={names} median={diag.get('median')}")

    tasks = start_venue_tasks(stop, cfg, assets, states, on_trade)
    print(f"Dry-run composite for {asset} · 60s · venues {list(states[asset].keys())}")
    end = time.time() + 60.0
    try:
        while time.time() < end:
            now = time.time()
            price, names, diag = compute_composite(states[asset], now=now, composite_cfg=comp_cfg)
            if price is not None:
                parts = [
                    f"{n}={diag['venues'][n]['mid']:.2f} dev={diag['venues'][n]['deviation_usd']:+.2f}"
                    for n in names
                    if n in diag.get("venues", {})
                ]
                print(f"composite={price:.4f} median={diag.get('median')} | " + " · ".join(parts))
            else:
                print("composite=— (waiting for venue ticks)")
            await asyncio.sleep(2.0)
    finally:
        stop.set()
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)


if __name__ == "__main__":
    asyncio.run(main())
