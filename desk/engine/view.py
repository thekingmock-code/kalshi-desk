"""Turn live numbers into the JSON the page renders."""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from desk.engine.chop import chop_label, chop_score
from desk.engine.gauge import build_gauge
from desk.engine.model import fair_up, fee_dollars
from desk.engine.rollover import Position
from desk.engine.strategies import all_pass, gate_sides
from desk.engine.suggest import SuggestCtx, decide

ET = ZoneInfo("America/New_York")


def et_stamp(ts: float) -> str:
    return datetime.fromtimestamp(ts, ET).strftime("%Y-%m-%d %I:%M:%S %p ET")


def build_asset(
    *,
    asset: str,
    now: float,
    cfg: dict,
    strategy: dict,
    market: dict,
    composite: float | None,
    composite_age: float | None,
    feeds: list[str],
    index: float | None,
    move_1m: float | None,
    baseline_move: float | None,
    buy_pct: float | None,
    momentum: int | None,
    crossings: int,
    position: Position | None,
    already_entered_hour: bool,
    paper_buys: int = 0,
    chart: dict | None = None,
) -> dict:
    fees = cfg["fees"]
    rate = float(fees["taker_rate"])
    strike = market.get("strike")
    close_ts = market.get("close_ts")
    secs_left = None if close_ts is None else close_ts - now
    ref = index if index is not None else composite
    lag = None if composite is None or index is None else composite - index
    move = move_1m or 0.0
    p_up, sigma_t, eff_s = (None, 0.0, 0.0)
    if ref is not None and strike is not None and secs_left is not None:
        p_up, sigma_t, eff_s = fair_up(ref, strike, move, secs_left, cfg["model"])
    leader = None if ref is None or strike is None else (1 if ref >= strike else -1)
    lead = None if ref is None or strike is None else ref - strike
    score, parts = chop_score(
        lead=lead,
        sigma_t=sigma_t if sigma_t > 0 else None,
        lag=lag,
        leader=leader,
        buy_pct=buy_pct,
        momentum=momentum,
        crossings=crossings,
        cfg=cfg["chop"],
    )
    label = chop_label(score, cfg["chop"])
    vol_ratio = None
    if move_1m and baseline_move and baseline_move > 0:
        vol_ratio = move_1m / baseline_move

    def fee_one(price: float) -> float:
        return fee_dollars(1, price, rate)

    gates = gate_sides(
        strategy,
        asset=asset,
        secs_left=secs_left,
        yes_bid=market.get("yes_bid"),
        yes_ask=market.get("yes_ask"),
        no_bid=market.get("no_bid"),
        no_ask=market.get("no_ask"),
        p_up=p_up,
        buy_pct=buy_pct,
        momentum=momentum,
        vol_ratio=vol_ratio,
        now=now,
        fee_fn=fee_one,
        already_entered_hour=already_entered_hour,
    )
    edge_up = None if p_up is None or market.get("yes_ask") is None else p_up - market["yes_ask"] - fee_one(market["yes_ask"])
    edge_down = None
    if p_up is not None and market.get("no_ask") is not None:
        edge_down = (1 - p_up) - market["no_ask"] - fee_one(market["no_ask"])
    if edge_down is not None and (edge_up is None or edge_down > edge_up):
        favored, favored_edge = "DOWN", edge_down
    elif edge_up is not None:
        favored, favored_edge = "UP", edge_up
    else:
        favored, favored_edge = None, None
    favored_pass = all_pass(gates[favored]) if favored else False

    trade = _trade(position, market, ref, strike, secs_left, lag, composite_age, rate, now, paper_buys, cfg)
    ctx = _ctx(trade, position, secs_left, p_up, market, favored, favored_edge, favored_pass, now, cfg, paper_buys)
    action, reasons = decide(ctx, cfg["suggest"], strategy)
    tone = _tone(action, trade.get("pnl"))
    tab_pos = "FLAT"
    tab_pnl = None
    if position and market.get("ticker") and position.ticker == market.get("ticker"):
        tab_pos = "UP" if position.side == "YES" else "DOWN"
        tab_pnl = trade.get("pnl")
    return {
        "tab": {
            "up": market.get("yes_ask"),
            "down": market.get("no_ask"),
            "secs_left": secs_left,
            "position": tab_pos,
            "pnl": tab_pnl,
        },
        "market": {
            "ticker": market.get("ticker"),
            "series": market.get("series"),
            "strike": strike,
            "close_ts": close_ts,
            "open_ts": market.get("open_ts"),
            "yes_bid": market.get("yes_bid"),
            "yes_ask": market.get("yes_ask"),
            "no_bid": market.get("no_bid"),
            "no_ask": market.get("no_ask"),
            "book": market.get("book", False),
        },
        "bot": {
            "composite": composite,
            "index": index,
            "lag": lag,
            "composite_age": composite_age,
            "feeds": feeds,
            "single_feed": len(feeds) == 1,
            "move_1m": move_1m,
            "vol_ratio": vol_ratio,
            "buy_pct": buy_pct,
            "momentum": momentum,
            "p_up": p_up,
            "eff_s": eff_s,
            "edge_up": edge_up,
            "edge_down": edge_down,
            "ref": ref,
        },
        "trade": trade,
        "suggestion": {"action": action, "tone": tone, "reasons": reasons},
        "chop": {"score": round(score, 1), "label": label, "parts": parts},
        "gates": gates,
        "gauge": build_gauge(
            composite=composite,
            strike=strike,
            move_1m=move_1m,
            baseline_move=baseline_move,
            secs_left=secs_left,
            favored=favored,
        ),
        "chart": chart or {"ok": False},
    }


def _trade(position, market, ref, strike, secs_left, lag, age, rate, now, paper_buys: int, cfg: dict) -> dict:
    paper_cfg = cfg.get("paper") or {}
    max_e = int(paper_cfg.get("max_entries_per_market", 2))
    if position is None or position.ticker != market.get("ticker"):
        return {
            "flat": True,
            "secs_left": secs_left,
            "lag": lag,
            "composite_age": age,
            "paper": False,
            "paper_entries_used": paper_buys,
            "paper_entries_max": max_e,
        }
    bid = market.get("yes_bid") if position.side == "YES" else market.get("no_bid")
    entry_fee = position.fees
    exit_fee = 0.0 if bid is None else fee_dollars(position.contracts, bid, rate)
    if position.entry is None:
        cost = value = pnl = None
    else:
        cost = position.entry * position.contracts + entry_fee
        value = None if bid is None else bid * position.contracts - exit_fee
        pnl = None if value is None else value - cost
    if ref is None or strike is None:
        right = None
    elif position.side == "YES":
        right = ref >= strike
    else:
        right = ref < strike
    return {
        "flat": False,
        "side": position.side,
        "entry": position.entry,
        "contracts": position.contracts,
        "cost": cost,
        "value": value,
        "pnl": pnl,
        "right": right,
        "bid": bid,
        "secs_left": secs_left,
        "lag": lag,
        "composite_age": age,
        "held_for": now - position.entry_ts,
        "high_water": position.high_water,
        "paper": bool(position.paper),
        "paper_entries_used": paper_buys,
        "paper_entries_max": max_e,
    }


def _ctx(trade, position, secs_left, p_up, market, favored, favored_edge, favored_pass, now, cfg, paper_buys) -> SuggestCtx:
    paper_cfg = cfg.get("paper") or {}
    enabled = bool(paper_cfg.get("enabled"))
    max_e = int(paper_cfg.get("max_entries_per_market", 2))
    if trade.get("flat"):
        reason = "no open 15m market" if not market.get("ticker") else "flat"
        return SuggestCtx(
            in_trade=False,
            favored=favored,
            favored_edge=favored_edge,
            gates_pass=favored_pass,
            flat_reason=reason,
            paper_enabled=enabled,
            paper_maxed=paper_buys >= max_e,
            paper_entries_used=paper_buys,
            paper_entries_max=max_e,
        )
    cost = trade["cost"] or 0
    pnl = trade["pnl"]
    loss = 0.0 if pnl is None or cost <= 0 or pnl >= 0 else (-pnl) / cost
    wrong = None if trade["right"] is None else not trade["right"]
    recover = None
    other_p = None
    other_ask = None
    if p_up is not None and position is not None:
        recover = p_up if position.side == "YES" else 1 - p_up
        other_p = 1 - recover
        other_ask = market.get("no_ask") if position.side == "YES" else market.get("yes_ask")
    return SuggestCtx(
        in_trade=True,
        loss_frac=loss,
        held_bid=trade.get("bid"),
        secs_left=secs_left,
        held_for=trade.get("held_for"),
        wrong=wrong,
        recover_p=recover,
        other_prob=other_p,
        other_ask=other_ask,
        pnl=pnl,
        high_water=position.high_water if position else None,
        entry=position.entry if position else None,
    )


def _tone(action: str, pnl: float | None) -> str:
    if action == "ENTER":
        return "profit"
    if action == "REVERSE":
        return "reverse"
    if action == "WAIT":
        return "wait"
    if action == "EXIT NOW":
        return "loss"
    if pnl is None:
        return "wait"
    if pnl > 0:
        return "profit"
    if pnl < 0:
        return "loss"
    return "wait"


def paper_journal_stats(rows: list[dict]) -> dict:
    settled = [r for r in rows if r.get("settled")]
    return journal_stats(
        [
            {
                "net_pnl": r.get("net_pnl"),
                "chop": r.get("chop"),
                "mode": "paper",
            }
            for r in settled
        ]
    )


def shadow_rows_for_ui(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        item = {
            "ts": r.get("entry_ts"),
            "asset": r.get("asset"),
            "side": r.get("side"),
            "entry": r.get("entry_ask"),
            "exit_px": r.get("exit_px"),
            "contracts": 1,
            "net_pnl": r.get("net_pnl"),
            "right": None if not r.get("settled") else bool(r.get("right")),
            "mode": "paper",
            "chop": r.get("chop"),
            "p_up": r.get("p_up"),
            "strike": r.get("strike"),
            "ticker": r.get("ticker"),
            "pending": not r.get("settled"),
            "gates": r.get("gates_json"),
        }
        if item["ts"]:
            item["et"] = et_stamp(float(item["ts"]))
        out.append(item)
    return out


def journal_stats(rows: list[dict]) -> dict:
    def wr(subset: list[dict]) -> float | None:
        if not subset:
            return None
        wins = sum(1 for r in subset if (r.get("net_pnl") or 0) > 0)
        return wins / len(subset)

    closed = [r for r in rows if r.get("mode") not in ("log",)]
    hi = [r for r in closed if r.get("chop") is not None and r["chop"] >= 70]
    lo = [r for r in closed if r.get("chop") is not None and r["chop"] < 40]
    net = sum((r.get("net_pnl") or 0) for r in closed)
    return {
        "trades": len(closed),
        "win_rate": wr(closed),
        "net_pnl": net,
        "win_rate_chop_70": wr(hi),
        "chop_70_n": len(hi),
        "win_rate_chop_40": wr(lo),
        "chop_40_n": len(lo),
    }


def stamp_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        item = dict(row)
        if item.get("ts"):
            item["et"] = et_stamp(float(item["ts"]))
        out.append(item)
    return out
