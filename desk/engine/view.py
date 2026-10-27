"""Turn live numbers into the JSON the page renders."""
from __future__ import annotations

import time
from datetime import datetime
from zoneinfo import ZoneInfo

from desk.engine.chop import chop_label, chop_score
from desk.engine.gauge import build_gauge
from desk.engine.model import fair_up, fee_dollars
from desk.engine.rollover import Position
from desk.engine.edge_modes import load_paper_modes
from desk.engine.gates_eval import net_edge, net_edge_entry
from desk.engine.strategies import all_pass, gate_sides
from desk.engine.tunable import merge_params
from desk.engine.paper import paper_entry_status
from desk.engine.suggest import SuggestCtx, decide

ET = ZoneInfo("America/New_York")


def _weekend_gate_summary(gates: dict) -> dict:
    def side_stats(side: str) -> dict:
        checks = gates.get(side) or []
        passing = sum(1 for c in checks if c.get("ok"))
        blocking = [c.get("label") for c in checks if not c.get("ok")]
        return {"passing": passing, "total": len(checks), "blocking": blocking}

    up, down = side_stats("UP"), side_stats("DOWN")
    fav = "UP" if up["passing"] >= down["passing"] else "DOWN"
    pick = up if fav == "UP" else down
    return {"favored_side": fav, **pick}


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
    dual_feed_ok: bool = False,
    feed_detail: str = "",
    composite_pct_move_3s: float | None = None,
    kalshi_mid_move_3s: float | None = None,
    btc_momentum: int | None = None,
    sol_confirm_secs: float | None = None,
    tunable_params: dict | None = None,
    paper_cooldown_ok: bool = True,
    paper_cooldown_remaining: float = 0.0,
    has_live_position: bool = False,
    index_ok: bool = False,
    momentum_30: int | None = None,
    momentum_60: int | None = None,
    signal_hold_secs: float | None = None,
    settings: dict | None = None,
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

    params = tunable_params or merge_params(strategy.get("id", "gates_15m"), asset, strategy.get("params"))
    strat = {**strategy, "params": params}
    yes_spread = (
        None
        if market.get("yes_ask") is None or market.get("yes_bid") is None
        else market["yes_ask"] - market["yes_bid"]
    )
    no_spread = (
        None
        if market.get("no_ask") is None or market.get("no_bid") is None
        else market["no_ask"] - market["no_bid"]
    )
    edge_up = net_edge(p_up, market.get("yes_ask"), yes_spread, fee_one)
    edge_down = net_edge(None if p_up is None else 1 - p_up, market.get("no_ask"), no_spread, fee_one)
    edge_up_entry = net_edge_entry(p_up, market.get("yes_ask"), fee_one)
    edge_down_entry = net_edge_entry(None if p_up is None else 1 - p_up, market.get("no_ask"), fee_one)
    paper_modes = load_paper_modes(settings or {})
    edge_basis = paper_modes.get("edge_basis", "net") if strat.get("id") == "gates_15m" else "net"
    yes_mid = None
    if market.get("yes_bid") is not None and market.get("yes_ask") is not None:
        yes_mid = (market["yes_bid"] + market["yes_ask"]) / 2
    no_mid = None
    if market.get("no_bid") is not None and market.get("no_ask") is not None:
        no_mid = (market["no_bid"] + market["no_ask"]) / 2
    market = {**market, "yes_mid": yes_mid, "no_mid": no_mid}
    gates = gate_sides(
        strat,
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
        params=params,
        sigma_t=sigma_t if sigma_t > 0 else None,
        ref=ref,
        strike=strike,
        dual_feed_ok=dual_feed_ok,
        feed_detail=feed_detail,
        composite_pct_move_3s=composite_pct_move_3s,
        kalshi_mid_move_3s=kalshi_mid_move_3s,
        btc_momentum=btc_momentum,
        sol_confirm_secs=sol_confirm_secs,
        index_ok=index_ok,
        lag=lag,
        momentum_30=momentum_30,
        momentum_60=momentum_60,
        signal_hold_secs=signal_hold_secs,
        edge_basis=edge_basis,
    )
    locked = [c for c in gates.get("UP", []) if c.get("locked")]
    gate_summary = None
    if strat.get("kind") == "weekend_money":
        gate_summary = _weekend_gate_summary(gates)
    if edge_down is not None and (edge_up is None or edge_down > edge_up):
        favored, favored_edge = "DOWN", edge_down
    elif edge_up is not None:
        favored, favored_edge = "UP", edge_up
    else:
        favored, favored_edge = None, None
    favored_pass = all_pass(gates[favored]) if favored else False

    trade = _trade(
        position,
        market,
        ref,
        strike,
        secs_left,
        lag,
        composite_age,
        rate,
        now,
        paper_buys,
        cfg,
        composite=composite,
    )
    ctx = _ctx(trade, position, secs_left, p_up, market, favored, favored_edge, favored_pass, now, cfg, paper_buys)
    action, reasons = decide(ctx, cfg["suggest"], strategy)
    tone = _tone(action, trade.get("pnl"))
    paper_entry = paper_entry_status(
        cfg=cfg,
        strategy=strat,
        market={
            "ticker": market.get("ticker"),
            "expired": bool(market.get("expired"))
            or (secs_left is not None and secs_left < 0),
            "yes_ask": market.get("yes_ask"),
            "no_ask": market.get("no_ask"),
            "yes_mid": yes_mid,
            "no_mid": no_mid,
        },
        trade=trade,
        bot={
            "edge_up": edge_up,
            "edge_down": edge_down,
            "edge_up_entry": edge_up_entry,
            "edge_down_entry": edge_down_entry,
            "p_up": p_up,
        },
        gates=gates,
        buys_so_far=paper_buys,
        cooldown_ok=paper_cooldown_ok,
        cooldown_remaining=paper_cooldown_remaining,
        has_live_position=has_live_position,
        settings=settings,
    )
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
            "edge_up_entry": edge_up_entry,
            "edge_down_entry": edge_down_entry,
            "ref": ref,
        },
        "trade": trade,
        "paper_entry": paper_entry,
        "suggestion": {"action": action, "tone": tone, "reasons": reasons},
        "chop": {"score": round(score, 1), "label": label, "parts": parts},
        "gates": gates,
        "locked_gates": locked,
        "gate_summary": gate_summary,
        "tunable_params": params,
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


def _trade(
    position,
    market,
    ref,
    strike,
    secs_left,
    lag,
    age,
    rate,
    now,
    paper_buys: int,
    cfg: dict,
    *,
    composite: float | None = None,
) -> dict:
    paper_cfg = cfg.get("paper") or {}
    max_e = int(paper_cfg.get("max_entries_per_market", 2))
    base = {
        "secs_left": secs_left,
        "lag": lag,
        "composite_age": age,
        "strike": strike,
        "composite": composite,
        "settle_ref": ref,
        "paper_entries_used": paper_buys,
        "paper_entries_max": max_e,
    }
    if position is None or position.ticker != market.get("ticker"):
        return {
            **base,
            "flat": True,
            "paper": False,
            "mode": "flat",
            "direction": None,
            "ticker": market.get("ticker"),
        }
    bid = market.get("yes_bid") if position.side == "YES" else market.get("no_bid")
    ask_side = market.get("yes_ask") if position.side == "YES" else market.get("no_ask")
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
        market_up = None
    else:
        market_up = ref >= strike
        if position.side == "YES":
            right = market_up
        else:
            right = not market_up
    direction = "UP" if position.side == "YES" else "DOWN"
    gap = None if composite is None or strike is None else round(composite - strike, 2)
    return {
        **base,
        "flat": False,
        "mode": "paper" if position.paper else "live",
        "direction": direction,
        "side": position.side,
        "ticker": position.ticker,
        "entry": position.entry,
        "entry_ts": position.entry_ts,
        "contracts": position.contracts,
        "cost": cost,
        "value": value,
        "pnl": pnl,
        "right": right,
        "direction_ok": right,
        "market_up": market_up,
        "gap_vs_strike": gap,
        "bid": bid,
        "ask": ask_side,
        "fees_paid": entry_fee,
        "held_for": now - position.entry_ts,
        "high_water": position.high_water,
        "chop_at_entry": position.chop,
        "paper": bool(position.paper),
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
    settled = [r for r in rows if r.get("settled") and r.get("right") is not None]
    return journal_stats(
        [
            {
                "net_pnl": r.get("net_pnl"),
                "chop": r.get("chop"),
                "mode": "paper",
                "right": bool(r.get("right")),
            }
            for r in settled
        ]
    )


def _shadow_direction(side: str | None) -> str | None:
    if side == "YES":
        return "UP"
    if side == "NO":
        return "DOWN"
    return None


def shadow_rows_for_ui(rows: list[dict]) -> list[dict]:
    out = []
    for r in rows:
        scored = bool(r.get("settled")) and r.get("right") is not None
        pick = _shadow_direction(r.get("side"))
        outcome = None
        if scored and r.get("up_won") is not None:
            outcome = "UP" if int(r["up_won"]) else "DOWN"
        dir_ok = None
        if scored and pick and outcome:
            dir_ok = pick == outcome
        item = {
            "ts": r.get("entry_ts"),
            "asset": r.get("asset"),
            "side": r.get("side"),
            "direction": pick,
            "outcome": outcome,
            "dir_ok": dir_ok,
            "entry": r.get("entry_ask"),
            "exit_px": r.get("exit_px"),
            "contracts": 1,
            "net_pnl": r.get("net_pnl"),
            "right": None if not scored else bool(r.get("right")),
            "mode": "paper",
            "chop": r.get("chop"),
            "p_up": r.get("p_up"),
            "strike": r.get("strike"),
            "settle_px": r.get("settle_composite"),
            "ticker": r.get("ticker"),
            "pending": not scored,
            "gates": r.get("gates_json"),
            "settle_note": r.get("settle_note"),
        }
        if item["ts"]:
            item["et"] = et_stamp(float(item["ts"]))
        out.append(item)
    return out


def journal_stats(rows: list[dict]) -> dict:
    def won(r: dict) -> bool:
        if r.get("right") is not None:
            return bool(r["right"])
        return (r.get("net_pnl") or 0) > 0

    def wr(subset: list[dict]) -> float | None:
        if not subset:
            return None
        wins = sum(1 for r in subset if won(r))
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


def fill_journal_rows_for_ui(rows: list[dict]) -> list[dict]:
    """Closed simulated fills from the journal table."""
    out = []
    for r in rows:
        mode = r.get("mode") or ""
        if "paper" not in mode:
            continue
        pick = _shadow_direction(r.get("side"))
        pnl = r.get("net_pnl")
        right = r.get("right")
        if right is None and pnl is not None:
            right = pnl > 0
        item = {
            "ts": r.get("ts"),
            "et": r.get("et"),
            "asset": r.get("asset"),
            "side": r.get("side"),
            "direction": pick,
            "outcome": None,
            "dir_ok": None if right is None else bool(right),
            "entry": r.get("entry"),
            "exit_px": r.get("exit"),
            "contracts": r.get("contracts"),
            "net_pnl": pnl,
            "right": right,
            "mode": mode,
            "chop": r.get("chop"),
            "p_up": None,
            "strike": None,
            "ticker": r.get("ticker"),
            "pending": False,
        }
        if item["ts"] and not item["et"]:
            item["et"] = et_stamp(float(item["ts"]))
        out.append(item)
    return out


def stamp_rows(rows: list[dict]) -> list[dict]:
    out = []
    for row in rows:
        item = dict(row)
        if item.get("ts"):
            item["et"] = et_stamp(float(item["ts"]))
        out.append(item)
    return out
