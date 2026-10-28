"""Spec checks for settlement, fees, chop, suggestions, and rollover."""
from __future__ import annotations

from desk.engine.chop import chop_score
from desk.engine.load import load_config
from desk.engine.model import composite_price, eff_seconds, fee_dollars, resolves_yes
from desk.engine.rollover import Book, Position, rollover
from desk.engine.suggest import SuggestCtx, decide
from desk.feeds.kalshi import parse_book, parse_index, pick_market

CFG = load_config()


def test_effs_continuous_at_60():
    assert eff_seconds(60) == 20
    assert (60 ** 3) / 10800 == 20
    assert eff_seconds(60) == (60 ** 3) / 10800


def test_tie_resolves_yes():
    assert resolves_yes(100.0, 100.0) is True
    assert resolves_yes(99.0, 100.0) is False


def test_exits_disabled_holds_to_settlement():
    rules = {**CFG["suggest"], "exits_enabled": False}
    action, reasons = decide(
        SuggestCtx(in_trade=True, loss_frac=0.99, held_bid=0.10, secs_left=10, held_for=999),
        rules,
    )
    assert action == "HOLD"
    assert any("settlement" in r.lower() for r in reasons)


def test_bank_95c_with_60s_left_exits():
    rules = {**CFG["suggest"], "exits_enabled": True}
    assert rules["bank_price"] == 0.95
    assert rules["bank_secs_left"] == 45
    action, _ = decide(
        SuggestCtx(in_trade=True, loss_frac=0.0, held_bid=0.95, secs_left=60, held_for=1),
        rules,
    )
    assert action == "EXIT NOW"


def test_loss_of_exactly_42_percent_exits():
    rules = {**CFG["suggest"], "exits_enabled": True}
    assert rules["exit_loss_frac"] == 0.42
    action, _ = decide(
        SuggestCtx(in_trade=True, loss_frac=0.42, held_bid=0.40, secs_left=200, held_for=1),
        rules,
    )
    assert action == "EXIT NOW"


def test_fee_rounding():
    assert fee_dollars(1, 0.50, 0.07) == 0.02
    assert fee_dollars(100, 0.50, 0.07) == 1.75


def test_stale_feed_is_ignored():
    now = 1_000.0
    price, names = composite_price(
        [("coinbase", 100.0, now), ("kraken", 300.0, now - 5.01)],
        now,
        5,
    )
    assert price == 100.0
    assert names == ["coinbase"]
    both, both_names = composite_price(
        [("coinbase", 100.0, now), ("kraken", 300.0, now - 5)],
        now,
        5,
    )
    assert both == 200.0
    assert both_names == ["coinbase", "kraken"]


def test_chop_caps_at_100():
    score, _ = chop_score(
        lead=1_000_000,
        sigma_t=1,
        lag=1,
        leader=1,
        buy_pct=100,
        momentum=1,
        crossings=0,
        cfg=CFG["chop"],
    )
    assert score == 100
    inflated = dict(CFG["chop"])
    inflated.update(
        cushion_max=90,
        lag_points=90,
        flow_max=90,
        momentum_aligned=90,
        crossings_0=90,
    )
    capped, _ = chop_score(
        lead=1_000_000,
        sigma_t=1,
        lag=1,
        leader=1,
        buy_pct=100,
        momentum=1,
        crossings=0,
        cfg=inflated,
    )
    assert capped == 100
    assert capped <= 100


def test_rollover_clears_book_and_auto_settles():
    pos = Position(
        asset="BTC",
        ticker="OLD",
        side="YES",
        contracts=2,
        entry=0.40,
        entry_ts=1,
        chop=88,
        fees=0.04,
        high_water=0.70,
    )
    book = Book(
        ticker="OLD",
        strike=100.0,
        yes_bid=0.61,
        yes_ask=0.62,
        no_bid=0.38,
        no_ask=0.39,
        crossings=3,
        last_sign=-1,
        position=pos,
        asset="BTC",
    )
    fresh, row = rollover(book, "NEW", 100.0)
    assert fresh.ticker == "NEW"
    assert fresh.strike is None
    assert fresh.yes_bid is None
    assert fresh.yes_ask is None
    assert fresh.no_bid is None
    assert fresh.no_ask is None
    assert fresh.position is None
    assert fresh.crossings == 0
    assert row["mode"] == "auto-settled"
    assert row["right"] is True
    assert row["exit"] == 1.0
    assert row["chop"] == 88
    same, nothing = rollover(fresh, "NEW", 100.0)
    assert same is fresh
    assert nothing is None


def test_index_payload_list_and_book_best_bid():
    price = parse_index({"data": {"payload": [{"value": "1"}, {"value": "80274.90"}]}})
    assert price == 80274.90
    book = parse_book(
        {
            "orderbook_fp": {
                "yes_dollars": [["0.10", "5"], ["0.61", "2"]],
                "no_dollars": [["0.20", "1"], ["0.38", "4"]],
            }
        }
    )
    assert book["yes_bid"] == 0.61
    assert book["no_bid"] == 0.38
    assert book["yes_ask"] == 0.62
    assert book["no_ask"] == 0.39


def test_pick_market_skips_a_closed_window():
    rows = [
        {
            "ticker": "KXBTC15M-CLOSED",
            "floor_strike": 1,
            "status": "open",
            "open_time": "1970-01-01T00:00:00+00:00",
            "close_time": "1970-01-01T00:15:00+00:00",
            "yes_ask_dollars": "0.40",
            "no_ask_dollars": "0.60",
        },
        {
            "ticker": "KXBTC15M-LIVE",
            "floor_strike": 2,
            "status": "open",
            "open_time": "1970-01-01T00:15:00+00:00",
            "close_time": "1970-01-01T00:30:00+00:00",
            "yes_ask_dollars": "0.55",
            "no_ask_dollars": "0.46",
        },
    ]
    picked = pick_market(rows, 1000.0)
    assert picked["ticker"] == "KXBTC15M-LIVE"
    assert picked["strike"] == 2
