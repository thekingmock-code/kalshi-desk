"""Simulated fills at live bid/ask. Never hits the Kalshi order API."""
from __future__ import annotations

from desk.engine.model import fee_dollars
from desk.engine.rollover import Position
from desk.engine.strategies import all_pass


def favored_side(bot: dict) -> tuple[str | None, float | None]:
    up, down = bot.get("edge_up"), bot.get("edge_down")
    if down is not None and (up is None or down > up):
        return "DOWN", down
    if up is not None:
        return "UP", up
    return None, None


def side_to_yes(side: str) -> str:
    return "YES" if side == "UP" else "NO"


def ask_for_side(market: dict, side: str) -> float | None:
    return market.get("yes_ask") if side == "UP" else market.get("no_ask")


def bid_for_side(market: dict, side: str) -> float | None:
    return market.get("yes_bid") if side == "UP" else market.get("no_bid")


def can_paper_enter(
    view: dict,
    *,
    cfg: dict,
    buys_so_far: int,
    cooldown_ok: bool,
    has_live_position: bool,
) -> tuple[bool, str]:
    paper = cfg.get("paper") or {}
    if not paper.get("enabled"):
        return False, "paper off"
    if has_live_position:
        return False, "live Kalshi position"
    strategy = view.get("_strategy")
    strategy = view.get("_strategy")
    if strategy and strategy.get("log_only"):
        return False, "log-only strategy"
    market = view.get("market") or {}
    if market.get("expired"):
        return False, "between rounds"
    ticker = market.get("ticker")
    if not ticker:
        return False, "no market"
    secs = view.get("trade", {}).get("secs_left")
    if secs is None or secs < 1:
        return False, "no time left"
    max_e = int(paper.get("max_entries_per_market", 2))
    if buys_so_far >= max_e:
        return False, f"{max_e}/{max_e} entries used"
    if not cooldown_ok:
        return False, "entry cooldown"
    favored, edge = favored_side(view.get("bot") or {})
    if not favored:
        return False, "no favored side"
    if paper.get("require_positive_edge", True) and (edge is None or edge <= 0):
        return False, "edge not positive"
    gates = view.get("gates") or {}
    if paper.get("require_gates", True) and not all_pass(gates.get(favored) or []):
        return False, "gates fail"
    ask = ask_for_side(market, favored)
    if ask is None or ask <= 0 or ask >= 1:
        return False, "no ask"
    return True, favored


def paper_buy(
    *,
    st,
    view: dict,
    side: str,
    now: float,
    cfg: dict,
    store,
    taker_rate: float,
) -> Position | None:
    market = view["market"]
    ticker = market["ticker"]
    ask = ask_for_side(market, side)
    if ask is None:
        return None
    contracts = float((cfg.get("paper") or {}).get("contracts", 1))
    fee = fee_dollars(contracts, ask, taker_rate)
    yes_no = side_to_yes(side)
    pos = st.book.position
    chop = view["chop"]["score"]
    if (
        pos
        and pos.paper
        and pos.ticker == ticker
        and pos.side == yes_no
        and pos.entry is not None
    ):
        total = pos.contracts + contracts
        pos.entry = (pos.entry * pos.contracts + ask * contracts) / total
        pos.contracts = total
        pos.fees += fee
        pos.high_water = max(pos.high_water, ask)
    else:
        pos = Position(
            asset=st.name,
            ticker=ticker,
            side=yes_no,
            contracts=contracts,
            entry=ask,
            entry_ts=now,
            chop=chop,
            fees=fee,
            high_water=ask,
            paper=True,
        )
        st.book.position = pos
    store.record_paper_buy(ticker)
    store.save_paper_open(st.name, pos)
    store.add_paper_order(
        asset=st.name,
        ticker=ticker,
        side=yes_no,
        action="buy",
        price=ask,
        contracts=contracts,
        fee=fee,
        edge=view["bot"].get("edge_up") if side == "UP" else view["bot"].get("edge_down"),
        chop=chop,
    )
    return pos
