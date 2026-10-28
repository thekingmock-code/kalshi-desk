"""Paper can add a second fill on the same market while holding (exits off)."""
from __future__ import annotations

from dataclasses import dataclass, field

from desk.engine.paper import paper_buy
from desk.engine.rollover import Book, Position
from desk.store import Store


@dataclass
class FakeAsset:
    name: str
    book: Book = field(default_factory=Book)
    last_paper_entry: float = 0.0


def test_paper_buy_averages_into_open_position(tmp_path):
    store = Store(tmp_path / "p.sqlite")
    st = FakeAsset("BTC")
    st.book.ticker = "KXBTC15M-X"
    st.book.position = Position(
        asset="BTC",
        ticker="KXBTC15M-X",
        side="YES",
        contracts=1.0,
        entry=0.45,
        entry_ts=100.0,
        chop=55.0,
        fees=0.02,
        high_water=0.45,
        paper=True,
    )
    view = {
        "market": {
            "ticker": "KXBTC15M-X",
            "yes_ask": 0.50,
            "no_ask": 0.51,
            "yes_bid": 0.49,
            "no_bid": 0.50,
        },
        "chop": {"score": 60.0},
        "bot": {"edge_up": 0.05, "edge_down": -0.02},
    }
    cfg = {"paper": {"enabled": True, "contracts": 1}}
    pos = paper_buy(
        st=st,
        view=view,
        side="UP",
        now=200.0,
        cfg=cfg,
        store=store,
        taker_rate=0.07,
    )
    assert pos is not None
    assert pos.contracts == 2.0
    assert pos.entry == 0.475
    assert store.paper_buy_count("KXBTC15M-X") == 1
