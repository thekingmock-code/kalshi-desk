# Generated chart artifacts

Run from the repo root:

```bash
python3 scripts/generate_trading_chart.py
```

Opens `generated/trading_chart.html` in a browser (needs network for the Lightweight Charts CDN).

The mock series includes composite candles, strike, required TWAP spot, and buy/sell markers from the rule-engine demo logic.
