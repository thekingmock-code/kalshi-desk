# Generated chart artifacts

Run from the repo root:

```bash
python3 scripts/generate_trading_chart.py
```

Opens `generated/trading_chart.html` in a browser (needs network for the Lightweight Charts CDN).

The standalone HTML uses mock data for offline demos. The desk **Features** tab chart uses **live composite ticks only** (no demo fallback).
