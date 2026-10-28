"""Simulated fills at live bid/ask. Never hits the Kalshi order API."""
from __future__ import annotations

from desk.engine.gates_eval import gate_edge_value
from desk.engine.edge_modes import (
    gate_mode_label,
    load_paper_modes,
    paper_edge_floor_ok,
    paper_gates_pass,
    pick_entry_side,
    resolve_gate_mode,
)
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


def lag_on_right_side(side: str, lag: float | None) -> bool:
    """UP needs composite above index (lag>0); DOWN needs lag<0."""
    if lag is None:
        return False
    if side == "UP":
        return lag > 0
    if side == "DOWN":
        return lag < 0
    return False


def ask_for_side(market: dict, side: str) -> float | None:
    return market.get("yes_ask") if side == "UP" else market.get("no_ask")


def bid_for_side(market: dict, side: str) -> float | None:
    return market.get("yes_bid") if side == "UP" else market.get("no_bid")


def first_gate_fail(checks: list[dict] | None) -> str | None:
    for c in checks or []:
        if not c.get("ok"):
            return c.get("label") or "gate"
    return None


def human_block_reason(reason: str, view: dict) -> str:
    bot = view.get("bot") or {}
    entry_side = view.get("_entry_side") or favored_side(bot)[0]
    edge = bot.get("edge_up") if entry_side == "UP" else bot.get("edge_down")
    if entry_side == "DOWN":
        edge = bot.get("edge_down")
    elif entry_side == "UP":
        edge = bot.get("edge_up")
    if reason == "gates fail" and entry_side:
        fail = first_gate_fail((view.get("gates") or {}).get(entry_side))
        if fail:
            return f"Gates fail: {fail} ({entry_side})"
        return "Gates fail"
    if reason == "edge floor":
        if entry_side and edge is not None:
            return f"Below edge floor ({entry_side} {edge * 100:+.1f}¢)"
        return "Below edge floor"
    if reason == "fade not triggered":
        return "Fade: model/mid divergence below trigger"
    if reason == "edge not positive":
        if entry_side and edge is not None:
            return f"Edge not positive ({entry_side} {edge * 100:+.1f}¢)"
        return "Edge not positive"
    return reason


def _paper_modes_for_view(view: dict, cfg: dict) -> dict:
    settings = view.get("_settings") or {}
    modes = load_paper_modes(settings)
    strategy = view.get("_strategy") or {}
    if strategy.get("id") != "gates_15m" or not (cfg.get("paper") or {}).get("enabled"):
        return load_paper_modes({})
    return modes


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

    bot = view.get("bot") or {}
    modes = _paper_modes_for_view(view, cfg)
    p_up = bot.get("p_up")
    yes_mid = market.get("yes_mid")
    if yes_mid is None and market.get("yes_bid") is not None and market.get("yes_ask") is not None:
        yes_mid = (market["yes_bid"] + market["yes_ask"]) / 2

    entry_side, _mode = pick_entry_side(
        edge_up=bot.get("edge_up"),
        edge_down=bot.get("edge_down"),
        modes=modes,
        p_up=p_up,
        yes_mid=yes_mid,
    )
    if not entry_side:
        if modes.get("fade_model") and strategy and strategy.get("id") == "gates_15m":
            return False, "fade not triggered"
        return False, "no favored side"

    basis = modes.get("edge_basis", "net")
    if entry_side == "UP":
        gate_edge = gate_edge_value(basis, bot.get("edge_up"), bot.get("edge_up_entry"))
    else:
        gate_edge = gate_edge_value(basis, bot.get("edge_down"), bot.get("edge_down_entry"))

    if strategy and strategy.get("id") == "gates_15m":
        if not paper_edge_floor_ok(gate_edge, modes):
            return False, "edge floor"
        gates = view.get("gates") or {}
        checks = gates.get(entry_side) or []
        if paper.get("require_gates", True) and not paper_gates_pass(
            checks, modes=modes, strategy_kind=strategy.get("kind", "gates")
        ):
            return False, "gates fail"
    else:
        favored, edge = favored_side(bot)
        if not favored:
            return False, "no favored side"
        entry_side = favored
        min_c = float(paper.get("min_net_edge_cents", 0))
        if edge is None or edge < min_c / 100.0:
            if paper.get("require_positive_edge", True) and (edge is None or edge <= 0):
                return False, "edge not positive"
        gates = view.get("gates") or {}
        if paper.get("require_gates", True) and not all_pass(gates.get(entry_side) or []):
            return False, "gates fail"

    ask = ask_for_side(market, entry_side)
    if ask is None or ask <= 0 or ask >= 1:
        return False, "no ask"
    return True, entry_side


def paper_entry_status(
    *,
    cfg: dict,
    strategy: dict,
    market: dict,
    trade: dict,
    bot: dict,
    gates: dict,
    buys_so_far: int,
    cooldown_ok: bool,
    cooldown_remaining: float,
    has_live_position: bool,
    settings: dict | None = None,
) -> dict:
    paper = cfg.get("paper") or {}
    enabled = bool(paper.get("enabled"))
    modes = load_paper_modes(settings or {})
    gate_mode = resolve_gate_mode(modes) if strategy.get("id") == "gates_15m" and enabled else "normal"
    mode_label = gate_mode_label(gate_mode)
    base = {
        "enabled": enabled,
        "can_enter": False,
        "favored": None,
        "reason": "",
        "status": "off",
        "gate_mode": gate_mode,
        "gate_mode_label": mode_label,
    }
    if not enabled:
        base["reason"] = "Paper off (observe only)"
        return base
    if not trade.get("flat"):
        if trade.get("paper"):
            base["status"] = "holding"
            base["reason"] = f"In paper {trade.get('direction') or 'position'} — hold to settlement (exits off)"
            base["favored"] = trade.get("direction")
            return base
        if has_live_position or trade.get("mode") == "live":
            base["status"] = "blocked"
            base["reason"] = "Live Kalshi position — paper entries blocked"
            return base
    view = {
        "_strategy": strategy,
        "_settings": settings or {},
        "market": market,
        "trade": trade,
        "bot": bot,
        "gates": gates,
    }
    ok, detail = can_paper_enter(
        view,
        cfg=cfg,
        buys_so_far=buys_so_far,
        cooldown_ok=cooldown_ok,
        has_live_position=has_live_position,
    )
    entry_side, _ = pick_entry_side(
        edge_up=bot.get("edge_up"),
        edge_down=bot.get("edge_down"),
        modes=modes if strategy.get("id") == "gates_15m" else load_paper_modes({}),
        p_up=bot.get("p_up"),
        yes_mid=market.get("yes_mid"),
    )
    view["_entry_side"] = detail if ok else entry_side
    if ok:
        return {
            **base,
            "can_enter": True,
            "favored": detail,
            "reason": f"Ready — next tick buys {detail} at live ask",
            "status": "ready",
        }
    reason_key = detail if detail in ("gates fail", "edge floor", "fade not triggered", "edge not positive") else detail
    reason = human_block_reason(reason_key, view) if reason_key in ("gates fail", "edge floor", "fade not triggered", "edge not positive") else detail.replace("_", " ")
    if detail == "entry cooldown" and cooldown_remaining > 0:
        reason = f"Entry cooldown ({cooldown_remaining:.0f}s left)"
    favored = view.get("_entry_side") or favored_side(bot)[0]
    return {
        **base,
        "can_enter": False,
        "favored": favored,
        "reason": reason,
        "status": "blocked",
    }


def contracts_for_max_usd(max_usd: float, ask: float, taker_rate: float) -> float:
    """Largest whole contract count with entry cost (ask + taker fee) <= max_usd."""
    if ask is None or ask <= 0 or ask >= 1 or max_usd <= 0:
        return 1.0
    best = 0
    for c in range(1, 5001):
        cost = c * ask + fee_dollars(c, ask, taker_rate)
        if cost <= max_usd + 1e-6:
            best = c
        else:
            break
    return float(max(best, 1))


def paper_entry_contracts(cfg: dict, ask: float, taker_rate: float) -> float:
    paper = cfg.get("paper") or {}
    if paper.get("max_trade_usd") is not None:
        return contracts_for_max_usd(float(paper["max_trade_usd"]), ask, taker_rate)
    return float(paper.get("contracts", 1))


def paper_buy(
    *,
    st,
    view: dict,
    side: str,
    now: float,
    cfg: dict,
    store,
    taker_rate: float,
    entry_log: dict | None = None,
) -> Position | None:
    market = view["market"]
    ticker = market["ticker"]
    ask = ask_for_side(market, side)
    if ask is None:
        return None
    contracts = paper_entry_contracts(cfg, ask, taker_rate)
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
    edge = view["bot"].get("edge_up") if side == "UP" else view["bot"].get("edge_down")
    store.add_paper_order(
        asset=st.name,
        ticker=ticker,
        side=yes_no,
        action="buy",
        price=ask,
        contracts=contracts,
        fee=fee,
        edge=edge,
        chop=chop,
    )
    if entry_log:
        store.add_paper_trade(
            ts=now,
            asset=st.name,
            ticker=ticker,
            side=yes_no,
            gate_mode=entry_log.get("gate_mode", "normal"),
            edge_net=entry_log.get("edge_net"),
            edge_entry=entry_log.get("edge_entry"),
            raw_prob_edge=entry_log.get("raw_prob_edge"),
            p_up=entry_log.get("p_up"),
            ask=entry_log.get("ask"),
            fee=entry_log.get("fee"),
            spread=entry_log.get("spread"),
            secs_left=entry_log.get("secs_left"),
            is_weekend=entry_log.get("is_weekend"),
            weekend_bump_applied=entry_log.get("weekend_bump_applied"),
        )
    return pos
