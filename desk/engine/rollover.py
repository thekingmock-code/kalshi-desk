"""Round change clears the book and auto-settles an open position."""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Position:
    asset: str
    ticker: str
    side: str  # YES or NO
    contracts: float
    entry: float | None
    entry_ts: float
    chop: float | None
    fees: float
    high_water: float
    paper: bool = False


@dataclass
class Book:
    ticker: str | None = None
    strike: float | None = None
    yes_bid: float | None = None
    yes_ask: float | None = None
    no_bid: float | None = None
    no_ask: float | None = None
    crossings: int = 0
    last_sign: int | None = None
    position: Position | None = None
    asset: str = ""


def rollover(book: Book, new_ticker: str | None, ref: float | None) -> tuple[Book, dict | None]:
    """If the ticker changed, settle against ref vs strike and blank prices."""
    if not book.ticker or not new_ticker or new_ticker == book.ticker:
        return book, None
    row = None
    if book.position and book.position.ticker == book.ticker:
        row = _auto_settle(book.position, book.strike, ref)
    blank = Book(
        ticker=new_ticker,
        strike=None,
        yes_bid=None,
        yes_ask=None,
        no_bid=None,
        no_ask=None,
        crossings=0,
        last_sign=None,
        position=None,
        asset=book.asset,
    )
    return blank, row


def _auto_settle(pos: Position, strike: float | None, ref: float | None) -> dict:
    yes = None if ref is None or strike is None else ref >= strike
    if yes is None:
        right = None
        exit_px = None
        pnl = None
    else:
        right = (pos.side == "YES" and yes) or (pos.side == "NO" and not yes)
        exit_px = 1.0 if right else 0.0
        pnl = None if pos.entry is None else (exit_px - pos.entry) * pos.contracts - pos.fees
    return {
        "asset": pos.asset,
        "ticker": pos.ticker,
        "side": pos.side,
        "entry": pos.entry,
        "exit": exit_px,
        "contracts": pos.contracts,
        "net_pnl": pnl,
        "right": right,
        "mode": "paper-settled" if pos.paper else "auto-settled",
        "chop": pos.chop,
        "entry_ts": pos.entry_ts,
    }
