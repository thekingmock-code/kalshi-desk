# Kalshi 15m edge scanner

Paper-trade / logging only: compares a driftless lognormal fair value (from Coinbase + Kraken spot and realized vol) against Kalshi 15-minute BTC and SOL binary markets. **Does not place orders.**

## Requirements

- Python 3.10+
- Network access to Coinbase, Kraken, and Kalshi public APIs

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## Run

```bash
python scanner.py
```

Stop with `Ctrl+C`. Signals append to `kalshi_edge_log.csv`.

## What it does

1. **Spot** — WebSocket tickers from Coinbase Advanced Trade and Kraken v2; composite mid when both feeds are fresh (≤ 5s).
2. **Vol** — Realized per-second σ from ~60+ seconds of composite log returns.
3. **Kalshi** — Polls open markets for series `KXBTC15M` and `KXSOL15M` every 2s (strike, yes/no ask, close time).
4. **Fair value** — `P(S_T > K) ≈ N(d2)` with no drift.
5. **Edge** — `fair − ask − fee`, where fee uses `0.07 × P × (1 − P)` (verify against [Kalshi’s fee schedule](https://kalshi.com)).
6. **Log** — Prints and CSV-logs when edge ≥ `MIN_EDGE` (default 5¢), subject to price ceiling, blackout window, and per-market cooldown.

## Configuration

Edit constants at the top of `scanner.py`:

| Constant | Default | Meaning |
|----------|---------|---------|
| `MIN_EDGE` | `0.05` | Minimum edge after fees to log |
| `PRICE_CEILING` | `0.25` | Skip sides with ask ≥ this (`None` to disable) |
| `BLACKOUT_SECS` | `120` | No signals in the last N seconds before close |
| `MIN_SAMPLES` | `60` | Seconds of history before vol is estimated |
| `COOLDOWN_SECS` | `60` | Min seconds between logs for same ticker + side |

## Model caveat

Kalshi 15m crypto markets settle on **CF Benchmarks BRTI** averages, not exchange spot. This scanner uses exchange composite price and `floor_strike` as a practical proxy; treat outputs as research signals, not guaranteed fair value vs settlement.

## API references

- [Kalshi market data quick start](https://docs.kalshi.com/getting_started/quick_start_market_data)
- [Kalshi API environments](https://docs.kalshi.com/getting_started/api_environments)
