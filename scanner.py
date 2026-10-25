"""
Kalshi 15m mispricing scanner (paper-trade / logging only, places NO orders).

Flow:
  CF Benchmarks (Kalshi passthrough) when creds set, else Coinbase + Kraken spot
  -> price history -> realized vol
  Kalshi open markets (strike, ask, close time)
  fair prob = N(d2)  ->  edge = fair prob - ask - fee  ->  log if edge >= MIN_EDGE
"""
import asyncio
import csv
import json
import math
import os
import time
import urllib.request
from collections import deque
from datetime import datetime, timezone

import websockets

from kalshi_auth import kalshi_get, load_private_key_from_env

# ====================== CONFIG ======================
LOG_FILE = "kalshi_edge_log.csv"
# Production Trade API (elections host is equivalent; see Kalshi docs)
KALSHI_BASE = os.environ.get(
    "KALSHI_API_BASE", "https://api.elections.kalshi.com/trade-api/v2"
)
SERIES = {"BTC": "KXBTC15M", "SOL": "KXSOL15M"}
# CF Benchmarks index IDs (Kalshi settlement reference)
CFB_INDEX = {"BTC": "BRTI", "SOL": "SOLUSD_RTI"}
CFB_POLL_SECS = 1.0

MIN_EDGE = 0.05  # require 5 points of edge after fees
PRICE_CEILING = 0.25  # risk filter only (None to disable); NOT the signal
BLACKOUT_SECS = 120  # no entries in final 2 minutes
MIN_SAMPLES = 60  # seconds of price history needed to estimate vol
COOLDOWN_SECS = 60  # one log per market+side per cooldown
STALE_SECS = 5  # ignore a feed if older than this
KALSHI_POLL_SECS = 2

# ====================== STATE ======================
state = {
    a: {
        "coinbase": (0.0, 0.0),  # (price, timestamp)
        "kraken": (0.0, 0.0),
        "cfb": (0.0, 0.0),  # CF Benchmarks RTI via Kalshi passthrough
        "history": deque(maxlen=600),  # 1 sample/sec, ~10 min
        "markets": [],
    }
    for a in SERIES
}
last_logged = {}  # (ticker, side) -> time
_kalshi_creds: tuple[str | None, object | None] = (None, None)


def init_log():
    if not os.path.exists(LOG_FILE):
        with open(LOG_FILE, "w", newline="") as f:
            csv.writer(f).writerow(
                [
                    "utc_time",
                    "asset",
                    "ticker",
                    "side",
                    "spot",
                    "price_source",
                    "strike",
                    "secs_left",
                    "sigma_T",
                    "fair_prob",
                    "ask",
                    "fee",
                    "edge",
                ]
            )


# ====================== MODEL ======================
def norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fair_prob_above(spot, strike, secs_left, sigma_per_sec):
    """P(spot at close > strike) under driftless lognormal: N(d2)."""
    sigma_T = max(sigma_per_sec * math.sqrt(max(secs_left, 1.0)), 1e-6)
    d2 = (math.log(spot / strike) - 0.5 * sigma_T**2) / sigma_T
    return norm_cdf(d2), sigma_T


def kalshi_fee(price):
    """Approx taker fee per contract in dollars (0.07*P*(1-P)). Verify vs fee schedule."""
    return 0.07 * price * (1.0 - price)


def realized_sigma_per_sec(history):
    prices = [p for p in history if p > 0]
    if len(prices) < MIN_SAMPLES:
        return None
    rets = [math.log(b / a) for a, b in zip(prices[:-1], prices[1:])]
    mean = sum(rets) / len(rets)
    var = sum((r - mean) ** 2 for r in rets) / max(len(rets) - 1, 1)
    return math.sqrt(var)


def composite_exchange(asset):
    s = state[asset]
    now = time.time()
    fresh = [
        p
        for p, ts in (s["coinbase"], s["kraken"])
        if p > 0 and now - ts <= STALE_SECS
    ]
    return sum(fresh) / len(fresh) if fresh else None


def mark_price(asset):
    """Settlement-aligned CF index when available, else exchange composite."""
    s = state[asset]
    now = time.time()
    p, ts = s["cfb"]
    if p > 0 and now - ts <= STALE_SECS:
        return p, "cfb"
    ex = composite_exchange(asset)
    if ex is not None:
        return ex, "exchange"
    return None, None


def _parse_cfb_value(body: dict) -> float | None:
    """Extract latest index level from Kalshi cfbenchmarks envelope."""
    data = body.get("data") or body
    payload = data.get("payload") if isinstance(data, dict) else None
    if isinstance(payload, list) and payload:
        raw = payload[-1].get("value")
    elif isinstance(payload, dict):
        raw = payload.get("value")
        if raw is None and payload.get("values"):
            vals = payload["values"]
            if vals:
                raw = vals[-1].get("value")
    else:
        return None
    if raw is None:
        return None
    return float(raw)


# ====================== SPOT FEEDS ======================
async def stream_coinbase():
    url = "wss://advanced-trade-ws.coinbase.com"
    products = [f"{a}-USD" for a in SERIES]
    while True:
        try:
            async with websockets.connect(url) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "type": "subscribe",
                            "product_ids": products,
                            "channel": "ticker",
                        }
                    )
                )
                print("Coinbase feed connected")
                async for raw in ws:
                    data = json.loads(raw)
                    for ev in data.get("events", []):
                        for t in ev.get("tickers", []):
                            asset = t["product_id"].split("-")[0]
                            if asset in state:
                                state[asset]["coinbase"] = (
                                    float(t["price"]),
                                    time.time(),
                                )
        except Exception as e:
            print(f"Coinbase error: {e}; reconnecting in 2s")
            await asyncio.sleep(2)


async def stream_kraken():
    url = "wss://ws.kraken.com/v2"
    symbols = [f"{a}/USD" for a in SERIES]
    while True:
        try:
            async with websockets.connect(url) as ws:
                await ws.send(
                    json.dumps(
                        {
                            "method": "subscribe",
                            "params": {"channel": "ticker", "symbol": symbols},
                        }
                    )
                )
                print("Kraken feed connected")
                async for raw in ws:
                    data = json.loads(raw)
                    if data.get("channel") == "ticker":
                        for u in data.get("data", []):
                            asset = u["symbol"].split("/")[0]
                            if asset in state:
                                state[asset]["kraken"] = (
                                    float(u["last"]),
                                    time.time(),
                                )
        except Exception as e:
            print(f"Kraken error: {e}; reconnecting in 2s")
            await asyncio.sleep(2)


# ====================== KALSHI MARKETS ======================
def _http_get(url):
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as r:
        return json.loads(r.read())


def _price(m, key):
    """Return price in dollars. Handles '<key>_dollars' or integer cents '<key>'."""
    if m.get(f"{key}_dollars") is not None:
        return float(m[f"{key}_dollars"])
    if m.get(key) is not None:
        return float(m[key]) / 100.0
    return None


async def poll_cfbenchmarks():
    """Kalshi-authenticated CF Benchmarks RTI (BRTI / SOLUSD_RTI)."""
    api_key_id, private_key = _kalshi_creds
    if not api_key_id or not private_key:
        return
    while True:
        for asset, index_id in CFB_INDEX.items():
            try:
                body = await asyncio.to_thread(
                    kalshi_get,
                    KALSHI_BASE,
                    api_key_id,
                    private_key,
                    "/cfbenchmarks/values",
                    query={"id": index_id},
                )
                price = _parse_cfb_value(body)
                if price is not None and price > 0:
                    state[asset]["cfb"] = (price, time.time())
            except Exception as e:
                print(f"CF Benchmarks poll error ({asset}/{index_id}): {e}")
        await asyncio.sleep(CFB_POLL_SECS)


async def poll_kalshi():
    """Public market data. Field names may differ: check Kalshi API docs."""
    while True:
        for asset, series in SERIES.items():
            try:
                url = (
                    f"{KALSHI_BASE}/markets"
                    f"?series_ticker={series}&status=open&limit=50"
                )
                data = await asyncio.to_thread(_http_get, url)
                out = []
                for m in data.get("markets", []):
                    strike = m.get("floor_strike") or m.get("cap_strike")
                    close = m.get("close_time")
                    yes_ask, no_ask = _price(m, "yes_ask"), _price(m, "no_ask")
                    if not (strike and close and yes_ask is not None and no_ask is not None):
                        continue
                    close_ts = datetime.fromisoformat(
                        close.replace("Z", "+00:00")
                    ).timestamp()
                    out.append(
                        {
                            "ticker": m["ticker"],
                            "strike": float(strike),
                            "close_ts": close_ts,
                            "yes_ask": yes_ask,
                            "no_ask": no_ask,
                        }
                    )
                state[asset]["markets"] = out
            except Exception as e:
                print(f"Kalshi poll error ({asset}): {e}")
        await asyncio.sleep(KALSHI_POLL_SECS)


# ====================== EVALUATOR ======================
def log_signal(row):
    with open(LOG_FILE, "a", newline="") as f:
        csv.writer(f).writerow(row)


async def evaluator():
    """Runs once per second: samples price, estimates vol, scans markets for edge."""
    while True:
        await asyncio.sleep(1.0)
        now = time.time()
        for asset, s in state.items():
            spot, source = mark_price(asset)
            if spot is None:
                continue
            s["history"].append(spot)
            sigma = realized_sigma_per_sec(s["history"])
            if sigma is None:
                continue

            for m in s["markets"]:
                secs_left = m["close_ts"] - now
                if secs_left <= BLACKOUT_SECS:
                    continue
                p_yes, sigma_T = fair_prob_above(
                    spot, m["strike"], secs_left, sigma
                )
                candidates = [
                    ("BUY_YES", p_yes, m["yes_ask"]),
                    ("BUY_NO", 1.0 - p_yes, m["no_ask"]),
                ]
                for side, fair, ask in candidates:
                    if PRICE_CEILING is not None and ask >= PRICE_CEILING:
                        continue
                    fee = kalshi_fee(ask)
                    edge = fair - ask - fee
                    key = (m["ticker"], side)
                    if (
                        edge >= MIN_EDGE
                        and now - last_logged.get(key, 0) > COOLDOWN_SECS
                    ):
                        last_logged[key] = now
                        ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
                        print(
                            f"[EDGE] {m['ticker']} {side} ask={ask:.2f} "
                            f"fair={fair:.2f} edge={edge:+.3f} left={secs_left:.0f}s "
                            f"src={source}"
                        )
                        log_signal(
                            [
                                ts,
                                asset,
                                m["ticker"],
                                side,
                                f"{spot:.2f}",
                                source,
                                m["strike"],
                                f"{secs_left:.0f}",
                                f"{sigma_T:.5f}",
                                f"{fair:.4f}",
                                f"{ask:.2f}",
                                f"{fee:.4f}",
                                f"{edge:.4f}",
                            ]
                        )


async def main():
    global _kalshi_creds
    init_log()
    _kalshi_creds = load_private_key_from_env()
    api_key_id, private_key = _kalshi_creds
    if api_key_id and private_key:
        print("Kalshi credentials found — using CF Benchmarks RTI for mark price")
    elif api_key_id:
        print("KALSHI_ACCESS_KEY set but no private key — exchange composite only")
    else:
        print("No Kalshi API creds — exchange composite only (set KALSHI_ACCESS_KEY)")
    print("Starting edge scanner (log only, no orders)...")
    tasks = [stream_coinbase(), stream_kraken(), poll_kalshi(), evaluator()]
    if api_key_id and private_key:
        tasks.append(poll_cfbenchmarks())
    await asyncio.gather(*tasks)


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nStopped. Log saved to", LOG_FILE)
