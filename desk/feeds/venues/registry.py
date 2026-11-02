"""Start enabled spot venues (one asyncio task each)."""
from __future__ import annotations

import asyncio
from typing import Any

from desk.feeds.venues.base import VenueAssetState
from desk.feeds.venues.bitstamp import BitstampVenue
from desk.feeds.venues.coinbase import CoinbaseVenue
from desk.feeds.venues.gemini import GeminiVenue
from desk.feeds.venues.kraken import KrakenVenue

VENUE_CLASSES = {
    "coinbase": CoinbaseVenue,
    "kraken": KrakenVenue,
    "bitstamp": BitstampVenue,
    "gemini": GeminiVenue,
}


def build_venue_states(cfg: dict, assets: dict) -> dict[str, dict[str, VenueAssetState]]:
    comp = cfg.get("composite") or {}
    enabled = comp.get("enabled_venues") or ["coinbase", "kraken"]
    out: dict[str, dict[str, VenueAssetState]] = {}
    for asset in assets:
        out[asset] = {}
        asset_cfg = (comp.get("assets") or {}).get(asset) or {}
        venues = asset_cfg.get("venues") or enabled
        for v in venues:
            if v in VENUE_CLASSES and _pair_for(assets[asset], v):
                out[asset][v] = VenueAssetState()
    return out


def _pair_for(meta: dict, venue: str) -> str | None:
    key = venue if venue in meta else None
    if key and meta.get(key):
        return str(meta[key])
    if venue == "coinbase" and meta.get("coinbase"):
        return meta["coinbase"]
    if venue == "kraken" and meta.get("kraken"):
        return meta["kraken"]
    if venue == "bitstamp" and meta.get("bitstamp"):
        return meta["bitstamp"]
    if venue == "gemini" and meta.get("gemini"):
        return meta["gemini"]
    return None


def venue_pair_maps(assets: dict, venue: str) -> dict[str, str]:
    pairs: dict[str, str] = {}
    for asset, meta in assets.items():
        p = _pair_for(meta, venue)
        if p:
            pairs[asset] = p
    return pairs


def start_venue_tasks(
    stop: asyncio.Event,
    cfg: dict,
    assets: dict,
    states: dict[str, dict[str, VenueAssetState]],
    on_trade: callable,
    on_book_extra: dict[str, callable] | None = None,
) -> list[asyncio.Task]:
    comp = cfg.get("composite") or {}
    enabled = comp.get("enabled_venues") or ["coinbase", "kraken"]
    tasks: list[asyncio.Task] = []
    for vname in enabled:
        cls = VENUE_CLASSES.get(vname)
        if not cls:
            continue
        pairs = venue_pair_maps({a: assets[a] for a in assets}, vname)
        if not pairs:
            continue
        venue = cls()
        v_states = {}
        for asset in pairs:
            if asset in states and vname in states[asset]:
                v_states[asset] = states[asset][vname]

        book_cb = (on_book_extra or {}).get(vname)

        async def _run(venue=venue, pairs=pairs, v_states=v_states, book_cb=book_cb) -> None:
            kwargs = {"on_book_extra": book_cb} if book_cb and vname in ("coinbase", "kraken") else {}
            await venue.start(stop, asset_pairs=pairs, states=v_states, on_trade=on_trade, **kwargs)

        tasks.append(asyncio.create_task(_run(), name=f"venue-{vname}"))
    return tasks
