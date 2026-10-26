"""Read-only Kalshi markets, books, index, positions, and fills."""
from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime, timezone

from kalshi_auth import kalshi_get

DEFAULT_BASE = "https://api.elections.kalshi.com/trade-api/v2"
UA = "xvantage-desk/1.0"


def api_base() -> str:
    return os.environ.get("KALSHI_API_BASE", DEFAULT_BASE).rstrip("/")


def public_get(path: str, query: dict | None = None, timeout: float = 8.0) -> dict:
    q = urllib.parse.urlencode(query) if query else ""
    url = f"{api_base()}{path}" + (f"?{q}" if q else "")
    req = urllib.request.Request(url, headers={"Accept": "application/json", "User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read())


def _f(value) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _price(row: dict, key: str) -> float | None:
    """`*_dollars` is already in dollars. The legacy field is integer cents."""
    dollars = row.get(f"{key}_dollars")
    if dollars is not None and dollars != "":
        return _f(dollars)
    cents = row.get(key)
    if cents is None or cents == "":
        return None
    num = _f(cents)
    if num is None:
        return None
    return num / 100.0


def _ts(value) -> float | None:
    if not value:
        return None
    text = str(value).replace("Z", "+00:00")
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return None


def parse_market(row: dict) -> dict | None:
    close_ts = _ts(row.get("close_time"))
    if close_ts is None:
        return None
    strike = _f(row.get("floor_strike"))
    if strike is None:
        strike = _f(row.get("cap_strike"))
    return {
        "ticker": row.get("ticker"),
        "title": row.get("title") or "",
        "strike": strike,
        "close_ts": close_ts,
        "open_ts": _ts(row.get("open_time")),
        "yes_bid": _price(row, "yes_bid"),
        "yes_ask": _price(row, "yes_ask"),
        "no_bid": _price(row, "no_bid"),
        "no_ask": _price(row, "no_ask"),
        "status": row.get("status"),
        "book": False,
    }


def pick_market(rows: list[dict], now: float) -> dict | None:
    """Current 15m window, else the next one that has not closed."""
    parsed = [m for m in (parse_market(r) for r in rows) if m and m.get("ticker")]
    live = []
    for m in parsed:
        open_ts = m["open_ts"] if m["open_ts"] is not None else 0
        if open_ts <= now and m["close_ts"] > now + 1:
            live.append(m)
    if live:
        return min(live, key=lambda m: m["close_ts"])
    future = [m for m in parsed if m["close_ts"] > now + 1]
    if future:
        return min(future, key=lambda m: m["close_ts"])
    return None


def fetch_market(series: str, now: float | None = None) -> dict | None:
    import time

    body = public_get("/markets", {"series_ticker": series, "status": "open", "limit": "20"})
    return pick_market(body.get("markets") or [], time.time() if now is None else now)


def _levels(raw) -> list[float]:
    prices = []
    for level in raw or []:
        if isinstance(level, (list, tuple)) and level:
            num = _f(level[0])
        elif isinstance(level, dict):
            num = _f(level.get("price_dollars") if level.get("price_dollars") is not None else level.get("price"))
        else:
            num = None
        if num is None:
            continue
        if num > 1.5:
            num = num / 100.0
        prices.append(num)
    return prices


def parse_book(body: dict) -> dict:
    """Best bid is the highest price. Ask is one minus the other side's bid."""
    fp = body.get("orderbook_fp") or body.get("orderbook") or {}
    yes_prices = _levels(fp.get("yes_dollars") or fp.get("yes"))
    no_prices = _levels(fp.get("no_dollars") or fp.get("no"))
    yes_bid = max(yes_prices) if yes_prices else None
    no_bid = max(no_prices) if no_prices else None
    return {
        "yes_bid": yes_bid,
        "no_bid": no_bid,
        "yes_ask": None if no_bid is None else round(1 - no_bid, 4),
        "no_ask": None if yes_bid is None else round(1 - yes_bid, 4),
        "book": bool(yes_prices or no_prices),
    }


def fetch_book(ticker: str) -> dict:
    body = public_get(f"/markets/{urllib.parse.quote(ticker, safe='')}/orderbook")
    return parse_book(body)


def parse_index(body: dict) -> float | None:
    data = body.get("data") or body
    payload = data.get("payload") if isinstance(data, dict) else None
    raw = None
    if isinstance(payload, list) and payload:
        raw = payload[-1].get("value")
    elif isinstance(payload, dict):
        raw = payload.get("value")
        if raw is None and payload.get("values"):
            vals = payload["values"]
            if vals:
                raw = vals[-1].get("value")
    return _f(raw)


def fetch_index(api_key_id: str, private_key, index_id: str) -> float | None:
    body = kalshi_get(api_base(), api_key_id, private_key, "/cfbenchmarks/values", query={"id": index_id})
    return parse_index(body)


def fetch_positions(api_key_id: str, private_key) -> list[dict]:
    body = kalshi_get(api_base(), api_key_id, private_key, "/portfolio/positions", query={"limit": "200"})
    rows = body.get("market_positions") or body.get("positions") or []
    return [r for r in rows if isinstance(r, dict)]


def fetch_fills(api_key_id: str, private_key, limit: int = 200) -> list[dict]:
    body = kalshi_get(
        api_base(),
        api_key_id,
        private_key,
        "/portfolio/fills",
        query={"limit": str(limit)},
    )
    rows = body.get("fills") or []
    return [r for r in rows if isinstance(r, dict)]


def parse_fill(row: dict) -> dict | None:
    ticker = row.get("ticker") or row.get("market_ticker")
    fill_id = row.get("fill_id") or row.get("trade_id")
    side = str(row.get("side") or "").lower()
    action = str(row.get("action") or "").lower()
    if not ticker or not fill_id or side not in ("yes", "no") or action not in ("buy", "sell"):
        return None
    count = _f(row.get("count_fp"))
    if count is None:
        count = _f(row.get("count"))
    if count is None or count <= 0:
        return None
    yes_px = _price(row, "yes_price")
    no_px = _price(row, "no_price")
    price = yes_px if side == "yes" else no_px
    if price is None and yes_px is not None:
        price = yes_px if side == "yes" else 1 - yes_px
    ts = _ts(row.get("created_time") or row.get("created_ts"))
    if ts is None:
        ts = datetime.now(timezone.utc).timestamp()
    return {
        "fill_id": str(fill_id),
        "ticker": ticker,
        "side": "YES" if side == "yes" else "NO",
        "action": action,
        "contracts": count,
        "price": price,
        "is_taker": bool(row.get("is_taker", True)),
        "fee": _f(row.get("fee_cost")),
        "ts": ts,
    }


def parse_position(row: dict) -> dict | None:
    ticker = row.get("ticker") or row.get("market_ticker")
    raw = row.get("position_fp")
    if raw is None:
        raw = row.get("position")
    qty = _f(raw)
    if not ticker or qty is None or qty == 0:
        return None
    contracts = abs(qty)
    exposure = _f(row.get("market_exposure_dollars"))
    if exposure is None:
        cents = _f(row.get("market_exposure"))
        exposure = None if cents is None else cents / 100.0
    fees = _f(row.get("fees_paid_dollars"))
    entry = None if exposure is None or contracts <= 0 else exposure / contracts
    if entry is not None and (entry <= 0 or entry >= 1):
        entry = None
    return {
        "ticker": ticker,
        "side": "YES" if qty > 0 else "NO",
        "contracts": contracts,
        "entry": entry,
        "fees": fees or 0.0,
    }
