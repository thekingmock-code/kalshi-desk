# Kalshi 15m trade desk

Desk for Kalshi 15-minute crypto markets: **BTC, BNB, and SOL**. It watches Coinbase, Kraken, and the public Kalshi book, suggests **HOLD**, **REVERSE**, **WAIT**, **ENTER** (paper), or **EXIT NOW**, and **paper-trades** at live ask/bid with real fee math. It never sends orders to Kalshi.

A phone-width page shows sticky asset tabs, the open trade, a chop-versus-real score, strategy gates, and an Eastern-time journal. Thresholds live in `desk/config.yaml`.

## Run

```bash
pip install -r requirements.txt
python -m uvicorn desk.app:app --host 0.0.0.0 --port 43123
```

Open [http://127.0.0.1:43123](http://127.0.0.1:43123). The page loads `/api/state` and then takes a push every second on `/ws`.

```bash
python -m pytest desk/tests -q
```

## Permanent dashboard (Ubuntu VPS)

For 24/7 access without keeping a laptop on, deploy to an **Ubuntu 24.04 LTS** VPS and run the desk under **systemd**. Step-by-step: **[deploy/VPS.md](deploy/VPS.md)**.

Quick path after `ssh ubuntu@YOUR_VPS_IP`:

```bash
git clone YOUR_REPO_URL ~/kalshi-desk
cd ~/kalshi-desk
REPO_URL=YOUR_REPO_URL bash deploy/install-vps.sh
```

Permanent HTTPS on your phone: **[deploy/CLOUDFLARE-TUNNEL.md](deploy/CLOUDFLARE-TUNNEL.md)** (buy domain on Cloudflare + free tunnel).

**Minimal steps (Zynoo + mockkingdesk.com):** **[deploy/START-HERE.md](deploy/START-HERE.md)** — paste one script in the VPS console.

## Kalshi index and positions

Copy `.env.example` and export the variables. With a key, the desk reads the CF Benchmarks index through Kalshi (`BRTI`, `BNBUSD_RTI`, `SOLUSD_RTI`) and your open positions. Without a key it still runs: the reference price is the Coinbase + Kraken composite, lag is unknown, and the page says positions are unavailable.

- `KALSHI_ACCESS_KEY` — API key id
- `KALSHI_PRIVATE_KEY` or `KALSHI_PRIVATE_KEY_PATH` — PEM private key
- `KALSHI_API_BASE` — optional, defaults to the production trade API

Do not commit keys. If a key was pasted into chat, revoke it and create a new one.

## What the model does

Kalshi settles a 15-minute market on the 60-second index average. YES wins when the closing average is greater than or equal to the opening average, so a tie is YES. The fair probability is a driftless normal around that line, using effective seconds that shrink through the last minute. Fees are the taker schedule rounded up to the next cent. Exits are marked at the bid.

The chop score is a hand-set mix of cushion, index lag, taker flow, momentum, and strike crossings. It is stored on each trade at entry so the journal can compare win rate when the score was at least 70 with win rate when it was under 40.

Public prints suggest the 15-minute BTC edge after fees is thin. Treat the suggestion as a watch list and check the journal before acting on it.

## Layout

```
desk/app.py            FastAPI app and /ws
desk/config.yaml       every threshold
desk/feeds/            Coinbase, Kraken, Kalshi (read-only)
desk/engine/           fair value, chop, suggestions, strategies
desk/store.py          SQLite journal and slider overrides
desk/static/index.html the page
```

The journal file is `desk/desk.sqlite` and is gitignored. Clear journal asks for a second tap.

### Paper trading

With `paper.enabled: true` in `desk/config.yaml` (default), the engine simulates taker **buys at the live ask** when the active strategy’s gates all pass on the favored side (positive edge required). It **exits at the bid** on the same rules as live suggestions. **At most two buy fills per 15m market ticker**, with a cooldown between entries. Rows are stored in the journal as `paper-closed` / `paper-settled` and in the `paper_orders` table. Turn off with `paper.enabled: false` for observe-only mode.

`scanner.py` is the older CSV edge logger. The Next.js chart in this repo is a separate signals view; this desk is the one-page trade screen.
