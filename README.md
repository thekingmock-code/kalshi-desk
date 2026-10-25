# XVANTAGE // SIGNALS

Paper-only 15-minute desk for Kalshi BTC and SOL markets, plus a Python logger. **Nothing in this repo places orders.**

## Web desk

Teaching chart (candles, EMA, bands, VWAP, strike, vol cone), live Up/Down ticket, and a strategy lab: edge, cushion, and momentum gates, exit rules, and a local journal.

```bash
npm install
npm run dev
```

Open [http://127.0.0.1:43123](http://127.0.0.1:43123). The page polls `/api/desk` every 2 seconds.

Optional CF Benchmarks index (BRTI / SOLUSD_RTI) uses the same env vars as the scanner (`.env.example`). Next.js reads them from the environment, not from a committed file. Without a key, the model uses the Coinbase + Kraken composite and the index field stays empty.

## Python scanner

Log-only edge scanner: composite spot, realized vol, Kalshi asks, CSV when edge clears `MIN_EDGE`.

## Requirements

- Python 3.10+
- Network access to Coinbase, Kraken, and Kalshi public APIs

## Setup

```bash
pip install -r requirements.txt
```

### Kalshi API (CF Benchmarks BRTI / SOLUSD_RTI)

Copy `.env.example` to `.env` (or export variables). The scanner uses Kalshi’s [CF Benchmarks REST passthrough](https://docs.kalshi.com/cfbenchmarks/rest-passthrough) when credentials are set:

- `KALSHI_ACCESS_KEY` — API key ID from Kalshi → Account & security → API Keys  
- `KALSHI_PRIVATE_KEY` or `KALSHI_PRIVATE_KEY_PATH` — PEM private key from key creation  

**Do not commit keys.** If a key was pasted into chat or committed, revoke it in Kalshi and create a new one.

Without credentials, the scanner falls back to Coinbase + Kraken composite spot.

## Run

```bash
# optional: export KALSHI_ACCESS_KEY and KALSHI_PRIVATE_KEY_PATH
python scanner.py
```

Stop with `Ctrl+C`. Signals append to `kalshi_edge_log.csv`.

## What it does

1. **Mark price** — CF Benchmarks RTI via Kalshi (`BRTI`, `SOLUSD_RTI`) when API creds are set; otherwise Coinbase + Kraken composite (≤ 5s stale filter).
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

Kalshi 15m crypto markets settle on **60-second CF Benchmarks averages** at window boundaries, not a single RTI tick. With Kalshi creds, mark price uses live RTI; vol is still estimated from recent RTI history. The lognormal `N(d2)` model and `floor_strike` remain approximations—validate against market rules before trading.

## API references

- [Kalshi market data quick start](https://docs.kalshi.com/getting_started/quick_start_market_data)
- [Kalshi API environments](https://docs.kalshi.com/getting_started/api_environments)
