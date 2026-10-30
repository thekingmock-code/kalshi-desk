"""One-second desk loop. Paper trades at live quotes; never sends Kalshi orders."""
from __future__ import annotations

import asyncio
import copy
import time
from collections import deque
import json
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from kalshi_auth import load_private_key_from_env

from desk.engine import locked as gate_locked
from desk.engine.load import load_config
from desk.engine.tunable import (
    clamp_param,
    clamp_shared_param,
    default_params,
    merge_params,
    merge_shared_params,
    pending_key,
    settings_key,
    shared_settings_key,
    shared_slider_defs,
    slider_defs,
)
from desk.engine.trade_log_meta import entry_log_meta
from desk.engine.measurements.prefs import MEASUREMENT_PREFS_KEY, load_measurement_prefs
from desk.engine.measurements.assemble import build_measurements
from desk.engine.measurements.analytics import measurement_analytics
from desk.engine.measurements.window_features import WindowFeatureState
from desk.engine.measurements.book_tracker import BookMetricsState
from desk.engine.measurements.liquidation import LiquidationState
from desk.engine.model import fair_up
from desk.engine.model import composite_price, fee_dollars, log_return_stdev, move_1m_from_returns  # fee_dollars used for paper exits
from desk.engine.rollover import Book, Position, _auto_settle, rollover
from desk.engine.balances import paper_summary, parse_kalshi_balance
from desk.engine.edge_modes import (
    PAPER_SETTINGS_KEY,
    default_paper_modes,
    entry_snapshot,
    load_paper_modes,
    paper_trade_analytics,
    resolve_gate_mode,
)
from desk.engine.weekend_money import (
    WEEKEND_PREFS_KEY,
    is_weekend,
    load_weekend_prefs,
    weekend_bump_for_params,
)
from desk.engine.chop_log import candidate_log_fields
from desk.engine.chop_log_analytics import chop_log_analytics
from desk.engine.chop_gates import CHOP_GATES_KEY, load_chop_gates, reset_chop_soft_defaults
from desk.engine.gate_utils import all_active_pass, checks_excluding_labels, find_gate, gate_snapshot_json
from desk.engine.gates_eval import GateContext
from desk.engine.weekend_money import cost_adjusted_edge_cents
from desk.engine.paper import ask_for_side, can_paper_enter, paper_buy, side_to_yes
from desk.engine.shadow import (
    calibration,
    gates_passed_labels,
    settle_shadow_row,
    should_log_shadow,
    side_edge_and_ask,
)
from desk.engine.strategies import all_pass
from desk.engine.view import (
    build_asset,
    et_stamp,
    fill_journal_rows_for_ui,
    journal_stats,
    paper_journal_stats,
    shadow_rows_for_ui,
    stamp_rows,
)
from desk.feeds import coinbase, kalshi, kraken
from desk.store import Store

ROOT = Path(__file__).resolve().parent


@dataclass
class AssetRT:
    name: str
    meta: dict
    coinbase: tuple[float, float] | None = None
    kraken: tuple[float, float] | None = None
    index: tuple[float, float] | None = None
    samples: deque = field(default_factory=deque)
    trades: deque = field(default_factory=deque)
    book: Book = field(default_factory=Book)
    market: dict = field(default_factory=dict)
    scan_at: dict = field(default_factory=dict)
    last_paper_entry: float = 0.0
    chart_ticker: str | None = None
    chart_points: deque = field(default_factory=deque)
    mid_history: deque = field(default_factory=deque)
    sol_confirm_side: str | None = None
    sol_confirm_since: float | None = None
    weekend_hold_side: str | None = None
    weekend_hold_since: float | None = None
    ref_samples: deque = field(default_factory=deque)
    last_meas: dict = field(default_factory=dict)
    last_composite: float | None = None
    last_kalshi_quote_ts: float = 0.0
    meas_window: WindowFeatureState = field(default_factory=WindowFeatureState)
    meas_book: BookMetricsState = field(default_factory=BookMetricsState)
    meas_liq: LiquidationState = field(default_factory=LiquidationState)

    def __post_init__(self) -> None:
        self.book.asset = self.name


class Desk:
    def __init__(self, store_path: Path | None = None):
        self.cfg = load_config()
        self.store = Store(store_path or ROOT / "desk.sqlite")
        purged = self.store.shadow_reset_invalid_settlements()
        if purged:
            print(f"Shadow journal: removed {purged} row(s) that lacked settlement scores")
        stale = self.store.shadow_purge_stale_open(time.time() - 1200)
        if stale:
            print(f"Shadow journal: removed {stale} unscored row(s) from prior windows")
        chop_stale = self.store.chop_shadow_purge_stale(time.time() - 1200)
        if chop_stale:
            print(f"Chop shadow: removed {chop_stale} unscored row(s) from prior windows")
        self.assets = {name: AssetRT(name, meta) for name, meta in self.cfg["assets"].items()}
        self.listeners: list[asyncio.Queue] = []
        self.authed = False
        paper_on = bool((self.cfg.get("paper") or {}).get("enabled"))
        self.auth_note = None
        if paper_on:
            self.auth_note = "Paper trading on live bid/ask · no real Kalshi orders"
        self._creds: tuple | None = None
        self._load_paper_positions()
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []
        self._seeded = False
        self._lock = asyncio.Lock()
        self._account_balance: dict | None = None

    async def start(self) -> None:
        paper_on = bool((self.cfg.get("paper") or {}).get("enabled"))
        key_id, private_key = load_private_key_from_env()
        self._creds = (key_id, private_key) if key_id and private_key else None
        if self._creds:
            self.authed = True
            if paper_on:
                self.auth_note = "Paper trading · live Kalshi positions synced when keyed"
            else:
                self.auth_note = None
        elif self.auth_note:
            print(self.auth_note)
        products = {name: st.meta["coinbase"] for name, st in self.assets.items()}
        symbols = {name: st.meta["kraken"] for name, st in self.assets.items()}
        self._tasks = [
            asyncio.create_task(coinbase.stream(products, self._on_coinbase, self._on_trade, self._stop), name="coinbase"),
            asyncio.create_task(kraken.stream(symbols, self._on_kraken, self._on_trade, self._stop), name="kraken"),
            asyncio.create_task(self._poll_markets(), name="markets"),
            asyncio.create_task(self._tick(), name="tick"),
        ]
        if self._creds:
            self._tasks.append(asyncio.create_task(self._poll_private(), name="kalshi-private"))
        prefs = load_measurement_prefs(self.store.settings())
        for st in self.assets.values():
            st.meas_liq.enabled = bool(prefs.get("liquidation"))

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)

    def _on_coinbase(self, asset: str, price: float, ts: float) -> None:
        st = self.assets.get(asset)
        if st:
            st.coinbase = (price, ts)

    def _on_kraken(self, asset: str, price: float, ts: float) -> None:
        st = self.assets.get(asset)
        if st:
            st.kraken = (price, ts)

    def _on_trade(self, asset: str, usd: float, is_buy: bool, ts: float) -> None:
        st = self.assets.get(asset)
        if st and usd > 0:
            st.trades.append((ts, usd, is_buy))

    async def _poll_markets(self) -> None:
        while not self._stop.is_set():
            for st in self.assets.values():
                try:
                    market = await asyncio.to_thread(kalshi.fetch_market, st.meta["series"])
                    if market:
                        try:
                            book = await asyncio.to_thread(kalshi.fetch_book, market["ticker"])
                        except Exception as exc:
                            book = {}
                            print(f"Kalshi book {st.name}: {exc.__class__.__name__}")
                        for key in (
                            "yes_bid",
                            "yes_ask",
                            "no_bid",
                            "no_ask",
                            "depth_yes_top3",
                            "depth_no_top3",
                        ):
                            if book.get(key) is not None:
                                market[key] = book[key]
                        if book.get("book"):
                            market["book"] = True
                        market["series"] = st.meta["series"]
                    async with self._lock:
                        self._apply_market(st, market, time.time())
                except Exception as exc:
                    print(f"Kalshi market {st.name}: {exc.__class__.__name__}")
            await asyncio.sleep(2)

    async def _poll_private(self) -> None:
        assert self._creds
        key_id, private_key = self._creds
        while not self._stop.is_set():
            try:
                indexes = {}
                for st in self.assets.values():
                    indexes[st.name] = await asyncio.to_thread(
                        kalshi.fetch_index, key_id, private_key, st.meta["index"]
                    )
                positions = await asyncio.to_thread(kalshi.fetch_positions, key_id, private_key)
                fills = await asyncio.to_thread(kalshi.fetch_fills, key_id, private_key)
                balance_body = await asyncio.to_thread(kalshi.fetch_balance, key_id, private_key)
                async with self._lock:
                    now = time.time()
                    for name, price in indexes.items():
                        if price and price > 0:
                            self.assets[name].index = (price, now)
                    self._account_balance = parse_kalshi_balance(balance_body)
                    self._apply_account(positions, fills, now)
                    self.authed = True
                    if bool((self.cfg.get("paper") or {}).get("enabled")):
                        self.auth_note = "Paper trading · live Kalshi positions synced when keyed"
                    else:
                        self.auth_note = None
            except Exception as exc:
                self.authed = False
                self.auth_note = "Kalshi auth failed · positions unavailable · observe only"
                print(f"Kalshi private read: {exc.__class__.__name__}")
            poll = float(self.cfg.get("feeds", {}).get("index_poll_secs", 3))
            await asyncio.sleep(poll)

    async def _tick(self) -> None:
        while not self._stop.is_set():
            started = time.time()
            try:
                async with self._lock:
                    self._sample(started)
                    payload = self._payload(started)
            except Exception as exc:
                print(f"Desk tick: {exc.__class__.__name__}: {exc}")
                await asyncio.sleep(1)
                continue
            for queue in list(self.listeners):
                if queue.full():
                    try:
                        queue.get_nowait()
                    except asyncio.QueueEmpty:
                        pass
                try:
                    queue.put_nowait(payload)
                except Exception:
                    pass
            await asyncio.sleep(max(0.05, 1.0 - (time.time() - started)))

    def snapshot(self) -> dict:
        return self._payload(time.time())

    def _balances_header(self, assets: dict, journal_rows: list[dict]) -> dict:
        paper_cfg = self.cfg.get("paper") or {}
        start = float(paper_cfg.get("starting_balance", 1000.0))
        mark_pnls: list[float] = []
        for built in assets.values():
            trade = built.get("trade") or {}
            if trade.get("paper") and not trade.get("flat") and trade.get("pnl") is not None:
                mark_pnls.append(float(trade["pnl"]))
        paper = paper_summary(
            starting_balance=start,
            journal_rows=journal_rows,
            open_mark_pnls=mark_pnls,
        )
        acct = self._account_balance or {}
        return {
            "account": {
                "available": acct.get("available"),
                "portfolio_value": acct.get("portfolio_value"),
                "ok": self.authed and acct.get("available") is not None,
            },
            "paper": {
                "equity": paper["equity"],
                "starting_balance": paper["starting_balance"],
            },
            "pnl": {
                "total": paper["total_pnl"],
                "realized": paper["realized_pnl"],
                "unrealized": paper["unrealized_pnl"],
            },
        }

    def _payload(self, now: float) -> dict:
        btc_mom = self._momentum(self.assets.get("BTC"), now, self._composite(self.assets.get("BTC"), now)[0] if self.assets.get("BTC") else None) if self.assets.get("BTC") else None
        assets = {}
        for name, st in self.assets.items():
            built = self._build_view(st, now, btc_momentum=btc_mom)
            metrics = self._metrics(st, now)
            built["bot"]["feed_ages"] = metrics["feed_ages"]
            built["market"]["expired"] = bool((st.market or {}).get("expired")) or (
                built["tab"]["secs_left"] is not None and built["tab"]["secs_left"] < 0
            )
            assets[name] = built
        rows = self.store.journal()
        shadow = self.store.shadow_all()
        paper_on = bool((self.cfg.get("paper") or {}).get("enabled"))
        saved = self.store.settings()
        paper_modes = load_paper_modes(saved) if paper_on else default_paper_modes()
        if paper_on:
            stamped = stamp_rows(rows)
            fill_rows = fill_journal_rows_for_ui(stamped)
            journal_block = {
                "stats": journal_stats(
                    [{"net_pnl": r.get("net_pnl"), "chop": r.get("chop"), "mode": r.get("mode"), "right": r.get("right")} for r in fill_rows]
                ),
                "stats_label": "paper fills",
                "rows": fill_rows,
                "legacy_rows": stamped,
            }
            calibration_rows = shadow
        else:
            journal_block = {
                "stats": paper_journal_stats(shadow),
                "stats_label": "paper",
                "rows": shadow_rows_for_ui(shadow),
                "legacy_rows": stamp_rows(rows),
            }
            calibration_rows = shadow
        strategies = []
        for sid, spec in self.cfg["strategies"].items():
            if spec.get("kind") == "hour" or sid == "hour_end":
                continue
            params = self._params_for(sid, "BTC", saved)
            strategies.append(
                {
                    "id": sid,
                    "label": spec["label"],
                    "kind": spec["kind"],
                    "log_only": bool(spec.get("log_only")),
                    "params": params,
                    "sliders": slider_defs(sid, "BTC") + shared_slider_defs("BTC"),
                }
            )
        return {
            "now": now,
            "et": et_stamp(now),
            "authed": self.authed,
            "auth_note": self.auth_note,
            "observe_only": not bool((self.cfg.get("paper") or {}).get("enabled")),
            "paper": self.cfg.get("paper") or {},
            "active": self._strategy("BTC")["id"],
            "param_log": stamp_rows(self.store.param_changes()),
            "strategies": strategies,
            "asset_order": list(self.assets),
            "assets": assets,
            "journal": journal_block,
            "calibration": calibration(calibration_rows),
            "scanner": stamp_rows(self.store.scans()),
            "paper_orders": stamp_rows(self.store.paper_orders()),
            "rules": self.cfg["suggest"],
            "paper_modes": paper_modes,
            "weekend_prefs": load_weekend_prefs(saved) if paper_on else {"timezone": "America/New_York"},
            "paper_analytics": paper_trade_analytics(self.store.paper_trades()) if paper_on else None,
            "measurement_prefs": load_measurement_prefs(saved) if paper_on else load_measurement_prefs({}),
            "measurement_analytics": measurement_analytics(self.store.paper_trades())
            if paper_on
            else None,
            "measurement_ticks": stamp_rows(self.store.measurement_ticks(60)) if paper_on else [],
            "paper_trade_log": stamp_rows(self.store.paper_trades(40)) if paper_on else [],
            "chop_gates": load_chop_gates(saved) if paper_on else load_chop_gates({}),
            "chop_log_analytics": chop_log_analytics(
                self.store.chop_candidates(),
                self.store.paper_trades(),
            )
            if paper_on
            else None,
            "balances": self._balances_header(assets, rows),
        }

    def _sample(self, now: float) -> None:
        for st in self.assets.values():
            self._expire(st, now)
            px, _, _ = self._composite(st, now)
            if px is not None:
                st.samples.append((now, px))
                strike = st.book.strike
                if strike is not None:
                    diff = px - strike
                    sign = 1 if diff > 0 else (-1 if diff < 0 else 0)
                    if sign != 0:
                        if st.book.last_sign is not None and sign != st.book.last_sign:
                            st.book.crossings += 1
                        st.book.last_sign = sign
            keep = float(self.cfg["feeds"]["sample_keep_secs"])
            while st.samples and now - st.samples[0][0] > keep:
                st.samples.popleft()
            flow = float(self.cfg["feeds"]["flow_window_secs"])
            while st.trades and now - st.trades[0][0] > flow:
                st.trades.popleft()
            pos = st.book.position
            if pos and pos.ticker == st.book.ticker:
                bid = st.book.yes_bid if pos.side == "YES" else st.book.no_bid
                if bid is not None:
                    pos.high_water = max(pos.high_water, bid)
            self._append_chart_point(st, now, px)
            yes_bid, yes_ask = st.book.yes_bid, st.book.yes_ask
            if yes_bid is not None and yes_ask is not None:
                st.mid_history.append((now, (yes_bid + yes_ask) / 2))
                while st.mid_history and now - st.mid_history[0][0] > 30:
                    st.mid_history.popleft()
            strat = self._strategy(st.name)
            if strat.get("kind") == "sol" and st.name == "SOL":
                view = self._build_view(st, now)
                side = "UP" if (view["bot"].get("edge_up") or -1) >= (view["bot"].get("edge_down") or -1) else "DOWN"
                pre = [c for c in view["gates"][side] if c["label"] != "3s entry confirm"]
                if all(c["ok"] for c in pre):
                    if st.sol_confirm_side != side:
                        st.sol_confirm_side = side
                        st.sol_confirm_since = now
                else:
                    st.sol_confirm_side = None
                    st.sol_confirm_since = None
            self._run_paper(st, now)
            self._maybe_scan(st, now)
            self._maybe_shadow(st, now)
            self._measurement_tick(st, now, px)

    def _measurement_tick(self, st: AssetRT, now: float, composite: float | None) -> None:
        if not (self.cfg.get("paper") or {}).get("enabled"):
            return
        prefs = load_measurement_prefs(self.store.settings())
        if not any(
            prefs.get(k)
            for k in ("settlement_window", "book_metrics", "window_features", "liquidation")
        ):
            return
        ref = self._ref(st, now) or composite
        if ref is not None:
            st.ref_samples.append((now, ref))
            while st.ref_samples and now - st.ref_samples[0][0] > 120:
                st.ref_samples.popleft()
        if composite is not None and st.last_composite is not None:
            shared = merge_shared_params(st.name, self.store.settings().get(shared_settings_key(st.name)))
            move_thr = float(shared.get("quote_lag_move_usd", 5.0))
            st.meas_book.on_composite_move(now, composite - st.last_composite, move_thr)
        if composite is not None:
            st.last_composite = composite
        market = st.market or {}
        close_ts = market.get("close_ts")
        strike = st.book.strike
        window = float(self.cfg["feeds"]["vol_window_secs"])
        samples = list(st.samples)
        move = move_1m_from_returns(log_return_stdev(samples, now, window), ref or composite)
        p_up = None
        if ref is not None and strike is not None and close_ts is not None:
            secs_left = close_ts - now
            p_up, _, _ = fair_up(ref, strike, move or 0.0, secs_left, self.cfg["model"])
        cb = st.coinbase[0] if st.coinbase else None
        kr = st.kraken[0] if st.kraken else None
        book = {
            "yes_bid": st.book.yes_bid,
            "yes_ask": st.book.yes_ask,
            "no_bid": st.book.no_bid,
            "no_ask": st.book.no_ask,
            "depth_yes_top3": market.get("depth_yes_top3"),
            "depth_no_top3": market.get("depth_no_top3"),
        }
        meas = build_measurements(
            prefs=prefs,
            samples=list(st.ref_samples),
            close_ts=close_ts,
            now=now,
            ref=ref,
            strike=strike,
            move_1m=move,
            p_up=p_up,
            book=book,
            book_state=st.meas_book,
            window_state=st.meas_window,
            liq_state=st.meas_liq,
            composite=composite,
            coinbase=cb,
            kraken=kr,
        )
        st.last_meas = meas
        ticker = st.book.ticker or market.get("ticker")
        self.store.add_measurement_tick(ts=now, asset=st.name, ticker=ticker, payload=meas)

    def _load_paper_positions(self) -> None:
        for row in self.store.load_paper_open():
            st = self.assets.get(row["asset"])
            if not st:
                continue
            st.book.position = Position(
                asset=row["asset"],
                ticker=row["ticker"],
                side=row["side"],
                contracts=float(row["contracts"]),
                entry=row["entry"],
                entry_ts=float(row["entry_ts"]),
                chop=row["chop"],
                fees=float(row["fees"] or 0),
                high_water=float(row["high_water"] or 0),
                paper=True,
            )

    def _paper_buys(self, st: AssetRT) -> int:
        ticker = st.book.ticker or (st.market or {}).get("ticker") or ""
        return self.store.paper_buy_count(ticker) if ticker else 0

    def _run_paper(self, st: AssetRT, now: float) -> None:
        if not (self.cfg.get("paper") or {}).get("enabled"):
            return
        strategy = self._strategy(st.name)
        if strategy.get("log_only"):
            return
        ticker = st.book.ticker or ""
        if not ticker:
            return
        buys = self._paper_buys(st)
        view = self._preview(st, now, strategy, buys)
        pos = st.book.position
        rate = float(self.cfg["fees"]["taker_rate"])
        paper_cfg = self.cfg.get("paper") or {}
        max_e = int(paper_cfg.get("max_entries_per_market", 2))
        cooldown = float(paper_cfg.get("entry_cooldown_secs", 30))
        cooldown_ok = now - st.last_paper_entry >= cooldown

        has_live = pos is not None and not pos.paper
        ok, detail = can_paper_enter(
            view,
            cfg=self.cfg,
            buys_so_far=buys,
            cooldown_ok=cooldown_ok,
            has_live_position=has_live,
        )
        if not ok:
            return
        if pos and pos.paper and pos.ticker == ticker and side_to_yes(detail) != pos.side:
            return
        settings = self.store.settings()
        prefs = load_weekend_prefs(settings)
        chop_prefs = load_chop_gates(settings)
        is_wk = is_weekend(now, prefs["timezone"])
        modes = load_paper_modes(settings)
        params = view.get("tunable_params") or strategy.get("params") or {}
        bump = (
            weekend_bump_for_params(params, is_weekend_flag=is_wk)
            if strategy.get("id") == "weekend_money"
            else 0.0
        )
        chop_meta = view.get("chop") or {}
        mkt = view.get("market") or {}
        side_checks = (view.get("gates") or {}).get(detail) or []
        bot = view.get("bot") or {}
        cheap_side = False
        for edge_k, ask_k in (("edge_up", "yes_ask"), ("edge_down", "no_ask")):
            edge_v = bot.get(edge_k)
            ask_v = mkt.get(ask_k)
            if edge_v is not None and ask_v is not None and ask_v < 0.05 and edge_v >= 0.05:
                cheap_side = True
        g2 = find_gate(side_checks, "G2 Direction")
        g3 = find_gate(side_checks, "G3 Settlement view")
        trade = view.get("trade") or {}
        log_fields = candidate_log_fields(
            original=chop_meta.get("score"),
            adjusted=chop_meta.get("score_adjusted"),
            threshold=float(chop_prefs.get("log_threshold", 30)),
            basis=str(chop_prefs.get("log_basis", "original")),
            secs_left=trade.get("secs_left"),
        )
        cost_adj = None
        if strategy.get("kind") == "weekend_money":
            ctx = GateContext(
                asset=st.name,
                side=detail,
                secs_left=trade.get("secs_left"),
                bid=mkt.get("yes_bid") if detail == "UP" else mkt.get("no_bid"),
                ask=ask_for_side(mkt, detail),
                prob=bot.get("p_up") if detail == "UP" else (None if bot.get("p_up") is None else 1 - bot["p_up"]),
                flow_pct=None,
                momentum=None,
                vol_ratio=None,
                sigma_t=None,
                ref=None,
                strike=mkt.get("strike"),
                dual_feed_ok=True,
                feed_detail="",
                p_up=bot.get("p_up"),
                yes_mid=mkt.get("yes_mid"),
                no_mid=mkt.get("no_mid"),
                net_edge=None,
                params=params,
                is_weekend=is_wk,
                taker_rate=rate,
                g4_cost_adjusted_enabled=bool(prefs.get("g4_cost_adjusted_enabled", True)),
                g4_cost_pad_cents=float(prefs.get("g4_cost_pad_cents", 0.5)),
            )
            cost_adj = cost_adjusted_edge_cents(ctx)
        ask = ask_for_side(mkt, detail)
        entry_fee = fee_dollars(1, ask, rate) if ask is not None else None
        self.store.add_chop_candidate(
            {
                "ts": now,
                "asset": st.name,
                "ticker": ticker,
                "strategy": strategy.get("id"),
                "side": side_to_yes(detail),
                "chop": chop_meta.get("score"),
                "chop_partial": chop_meta.get("chop_partial"),
                "missing_rows": chop_meta.get("missing_rows"),
                "gate_layer_result": "log_only",
                "chop_addon_cents": 0.0,
                "block_reason": None,
                "would_have_entered": True,
                "taken": True,
                "entry_ask": ask,
                "fee": entry_fee,
                "shadow_id": None,
                "gate_snapshot": gate_snapshot_json(side_checks),
                "cost_adjusted_edge": cost_adj,
                "cheap_side_model_edge": cheap_side,
                "g2_passed": None if g2 is None else g2.get("status") == "pass" or g2.get("ok"),
                "g3_passed": None if g3 is None else g3.get("status") == "pass" or g3.get("ok"),
                **log_fields,
            }
        )
        st.last_paper_entry = now
        gate_mode = resolve_gate_mode(modes) if strategy.get("id") == "gates_15m" else "normal"
        bot = view.get("bot") or {}
        trade = view.get("trade") or {}
        hour_et, session = entry_log_meta(now, tz=prefs["timezone"])
        meas_snap = dict(st.last_meas) if st.last_meas else {}
        entry_log = entry_snapshot(
            side=detail,
            bot=bot,
            market=mkt,
            p_up=bot.get("p_up"),
            yes_mid=mkt.get("yes_mid"),
            no_mid=mkt.get("no_mid"),
            secs_left=trade.get("secs_left"),
            fee_fn=lambda p: fee_dollars(1, p, rate),
            gate_mode=gate_mode,
            is_weekend=is_wk,
            weekend_bump_applied=bump,
            strategy_id=strategy.get("id"),
            hour_et=hour_et,
            session=session,
        )
        entry_log["meas_json"] = meas_snap
        paper_buy(
            st=st,
            view=view,
            side=detail,
            now=now,
            cfg=self.cfg,
            store=self.store,
            taker_rate=rate,
            entry_log=entry_log,
        )

    def _paper_close(self, st: AssetRT, pos: Position, now: float, rate: float) -> None:
        bid = self._exit_bid(st, pos)
        exit_fee = 0.0 if bid is None else fee_dollars(pos.contracts, bid, rate)
        self._journal_close(st, pos, pos.contracts, bid, exit_fee, now, "paper-closed")
        self.store.add_paper_order(
            asset=st.name,
            ticker=pos.ticker,
            side=pos.side,
            action="sell",
            price=bid,
            contracts=pos.contracts,
            fee=exit_fee,
            edge=None,
            chop=pos.chop,
            ts=now,
        )
        self.store.clear_paper_open(st.name)
        st.book.position = None

    def _maybe_scan(self, st: AssetRT, now: float) -> None:
        strategy = self._strategy(st.name)
        if not strategy.get("log_only"):
            return
        view = self._preview(st, now, strategy)
        for side in ("UP", "DOWN"):
            if not all_pass(view["gates"][side]):
                continue
            ticker = view["market"].get("ticker") or ""
            if now - st.scan_at.get((ticker, side), 0) < 30:
                continue
            ask = view["market"].get("yes_ask") if side == "UP" else view["market"].get("no_ask")
            edge = view["bot"].get("edge_up") if side == "UP" else view["bot"].get("edge_down")
            self.store.add_scan(st.name, side, ask, edge)
            st.scan_at[(ticker, side)] = now

    def _build_view(self, st: AssetRT, now: float, *, btc_momentum: int | None = None, paper_buys: int | None = None) -> dict:
        strategy = self._strategy(st.name)
        if paper_buys is None:
            paper_buys = self._paper_buys(st)
        sol_confirm = self._sol_confirm_secs(st, now, strategy)
        metrics = self._metrics(st, now)
        self._tick_weekend_hold(st, now, strategy, metrics)
        signal_hold = self._weekend_signal_secs(st, now, strategy)
        paper_cfg = self.cfg.get("paper") or {}
        cooldown = float(paper_cfg.get("entry_cooldown_secs", 30))
        cooldown_remaining = max(0.0, cooldown - (now - st.last_paper_entry))
        cooldown_ok = cooldown_remaining <= 0
        pos = st.book.position
        has_live = pos is not None and not pos.paper
        return build_asset(
            asset=st.name,
            now=now,
            cfg=self.cfg,
            strategy=strategy,
            settings=self.store.settings(),
            market=self._market_view(st),
            composite=metrics["composite"],
            composite_age=metrics["composite_age"],
            feeds=metrics["feeds"],
            index=metrics["index"],
            move_1m=metrics["move_1m"],
            baseline_move=metrics["baseline_move"],
            buy_pct=metrics["buy_pct"],
            momentum=metrics["momentum"],
            crossings=metrics["crossings"],
            position=st.book.position,
            already_entered_hour=self._already_entered_hour(st.name, now),
            paper_buys=paper_buys,
            chart=self._chart_payload(st),
            dual_feed_ok=metrics["dual_feed_ok"],
            feed_detail=metrics["feed_detail"],
            composite_pct_move_3s=metrics["composite_pct_move_3s"],
            kalshi_mid_move_3s=metrics["kalshi_mid_move_3s"],
            btc_momentum=btc_momentum,
            sol_confirm_secs=sol_confirm,
            tunable_params=metrics["tunable_params"],
            paper_cooldown_ok=cooldown_ok,
            paper_cooldown_remaining=cooldown_remaining,
            has_live_position=has_live,
            index_ok=metrics["index"] is not None,
            momentum_30=metrics.get("momentum_30"),
            momentum_60=metrics.get("momentum_60"),
            signal_hold_secs=signal_hold,
            feed_ages=metrics.get("feed_ages"),
            measurements=st.last_meas,
        )

    def _preview(self, st: AssetRT, now: float, strategy: dict, paper_buys: int | None = None) -> dict:
        del strategy
        btc_st = self.assets.get("BTC")
        btc_mom = None
        if btc_st:
            px, _, _ = self._composite(btc_st, now)
            btc_mom = self._momentum(btc_st, now, px)
        view = self._build_view(st, now, btc_momentum=btc_mom, paper_buys=paper_buys)
        view["_strategy"] = self._strategy(st.name)
        return view

    def _apply_market(self, st: AssetRT, market: dict | None, now: float) -> None:
        if not market:
            self._expire(st, now)
            return
        if st.meas_window.ticker != market.get("ticker"):
            st.meas_window.reset(market.get("ticker"))
        if st.book.ticker and market["ticker"] != st.book.ticker:
            new_book, row = rollover(st.book, market["ticker"], self._ref(st, now))
            if row:
                row["ts"] = now
                self.store.add_journal(row)
                if st.book.position and st.book.position.paper:
                    pos = st.book.position
                    ref = self._ref(st, now)
                    strike = st.book.strike
                    up_won = None if ref is None or strike is None else ref >= strike
                    self.store.settle_paper_trade(
                        pos.asset,
                        pos.ticker,
                        pos.side,
                        up_won=up_won,
                        net_pnl=row.get("net_pnl"),
                        right=row.get("right"),
                    )
                    self.store.clear_paper_open(st.name)
            self._settle_shadow(st, self._settlement_ref(st, now))
            self._settle_chop_shadow(st, self._settlement_ref(st, now))
            self._apply_pending_params(st.name)
            st.book = new_book
            st.chart_ticker = new_book.ticker
            st.chart_points.clear()
            st.mid_history.clear()
            st.sol_confirm_since = None
            st.sol_confirm_side = None
            st.book.asset = st.name
        ticker = market["ticker"]
        if ticker and st.meas_window.ticker != ticker:
            st.meas_window.reset(ticker)
        st.book.ticker = ticker
        st.book.asset = st.name
        st.book.strike = market.get("strike")
        for key in ("yes_bid", "yes_ask", "no_bid", "no_ask"):
            if market.get(key) is not None:
                setattr(st.book, key, market[key])
                st.last_kalshi_quote_ts = now
        st.meas_book.on_book(
            now,
            {
                "yes_bid": market.get("yes_bid"),
                "yes_ask": market.get("yes_ask"),
                "no_bid": market.get("no_bid"),
                "no_ask": market.get("no_ask"),
                "depth_yes_top3": market.get("depth_yes_top3"),
                "depth_no_top3": market.get("depth_no_top3"),
            },
        )
        st.market = market
        if market and market.get("ticker") and market["ticker"] != st.chart_ticker:
            st.chart_ticker = market["ticker"]
            st.chart_points.clear()

    def _append_chart_point(self, st: AssetRT, now: float, composite: float | None) -> None:
        ticker = st.book.ticker or (st.market or {}).get("ticker")
        if not ticker or composite is None:
            return
        if st.chart_ticker != ticker:
            st.chart_ticker = ticker
            st.chart_points.clear()
        stale = float(self.cfg["feeds"]["stale_secs"])
        cb = st.coinbase[0] if st.coinbase and now - st.coinbase[1] <= stale else None
        kr = st.kraken[0] if st.kraken and now - st.kraken[1] <= stale else None
        st.chart_points.append(
            {
                "t": now,
                "c": composite,
                "cb": cb,
                "kr": kr,
                "s": st.book.strike,
            }
        )
        while len(st.chart_points) > 960:
            st.chart_points.popleft()

    def _chart_payload(self, st: AssetRT) -> dict:
        market = st.market or {}
        open_ts = market.get("open_ts")
        close_ts = market.get("close_ts")
        if not st.chart_points:
            return {"ok": False}
        points = []
        for pt in st.chart_points:
            rel = pt["t"] - open_ts if open_ts is not None else pt["t"]
            points.append(
                {
                    "t": round(rel, 1),
                    "c": pt["c"],
                    "cb": pt["cb"],
                    "kr": pt["kr"],
                    "s": pt["s"],
                }
            )
        last = st.chart_points[-1]
        return {
            "ok": True,
            "open_ts": open_ts,
            "close_ts": close_ts,
            "grace_secs": float(self.cfg["suggest"]["entry_grace_secs"]),
            "safeguard_secs": 60.0,
            "strike": st.book.strike,
            "points": points,
            "current": {
                "c": last["c"],
                "cb": last["cb"],
                "kr": last["kr"],
                "s": last["s"],
            },
        }

    def _maybe_shadow(self, st: AssetRT, now: float) -> None:
        if (self.cfg.get("paper") or {}).get("enabled"):
            return
        strategy = self._strategy(st.name)
        if strategy.get("log_only"):
            return
        ticker = st.book.ticker
        if not ticker or (st.market or {}).get("expired"):
            return
        view = self._preview(st, now, strategy)
        strike = st.book.strike
        for side in ("UP", "DOWN"):
            if not should_log_shadow(side, view):
                continue
            edge, ask = side_edge_and_ask(view.get("market") or {}, view.get("bot") or {}, side)
            gates = view.get("gates") or {}
            self.store.shadow_try_insert(
                {
                    "ticker": ticker,
                    "asset": st.name,
                    "side": "YES" if side == "UP" else "NO",
                    "entry_ts": now,
                    "entry_ask": ask,
                    "p_up": view.get("bot", {}).get("p_up"),
                    "chop": view.get("chop", {}).get("score"),
                    "strike": strike,
                    "gates_json": json.dumps(
                        {"passed": gates_passed_labels(gates.get(side) or []), "side": side, "edge": edge}
                    ),
                }
            )

    def _settlement_ref(self, st: AssetRT, now: float) -> float | None:
        ref = self._ref(st, now)
        if ref is not None:
            return ref
        if st.samples:
            return st.samples[-1][1]
        return None

    def _settle_shadow(self, st: AssetRT, ref: float | None) -> None:
        ticker = st.book.ticker or (st.market or {}).get("ticker")
        if not ticker:
            return
        book_strike = st.book.strike
        rate = float(self.cfg["fees"]["taker_rate"])
        for row in self.store.shadow_unsettled(ticker):
            strike = book_strike if book_strike is not None else row.get("strike")
            settled = settle_shadow_row(dict(row), ref, strike, rate)
            self.store.shadow_settle_row(
                row["id"],
                {
                    "settle_composite": settled.get("settle_composite"),
                    "up_won": settled.get("up_won"),
                    "right": settled.get("right"),
                    "exit_px": settled.get("exit_px"),
                    "net_pnl": settled.get("net_pnl"),
                    "settle_note": settled.get("settle_note"),
                },
            )

    def _settle_chop_shadow(self, st: AssetRT, ref: float | None) -> None:
        ticker = st.book.ticker or (st.market or {}).get("ticker")
        if not ticker:
            return
        book_strike = st.book.strike
        rate = float(self.cfg["fees"]["taker_rate"])
        for row in self.store.chop_shadow_unsettled(ticker):
            strike = book_strike if book_strike is not None else row.get("strike")
            settled = settle_shadow_row(
                {**dict(row), "strike": strike},
                ref,
                strike,
                rate,
            )
            self.store.chop_shadow_settle_row(
                row["id"],
                {
                    "settle_composite": settled.get("settle_composite"),
                    "up_won": settled.get("up_won"),
                    "right": settled.get("right"),
                    "exit_px": settled.get("exit_px"),
                    "net_pnl": settled.get("net_pnl"),
                    "settle_note": settled.get("settle_note"),
                },
            )

    def _expire(self, st: AssetRT, now: float) -> None:
        close_ts = (st.market or {}).get("close_ts")
        if close_ts is None or now < close_ts:
            return
        ref = self._settlement_ref(st, now)
        self._settle_shadow(st, ref)
        self._settle_chop_shadow(st, ref)
        pos = st.book.position
        if pos and pos.ticker == (st.book.ticker or st.market.get("ticker")):
            row = _auto_settle(pos, st.book.strike, ref)
            row["ts"] = now
            self.store.add_journal(row)
            if pos.paper:
                self.store.clear_paper_open(st.name)
            st.book.position = None
        st.book.strike = None
        st.book.yes_bid = None
        st.book.yes_ask = None
        st.book.no_bid = None
        st.book.no_ask = None
        st.book.crossings = 0
        st.book.last_sign = None
        st.market = {"ticker": st.book.ticker, "close_ts": close_ts, "expired": True}

    def _apply_account(self, positions: list[dict], fills: list[dict], now: float) -> None:
        parsed = [f for f in (kalshi.parse_fill(r) for r in fills) if f]
        parsed.sort(key=lambda f: f["ts"])
        if not self._seeded:
            for fill in parsed:
                self.store.mark_fill(fill["fill_id"], fill["ts"])
            self._seed_positions(positions, now)
            self._seeded = True
            return
        for fill in parsed:
            if self.store.seen_fill(fill["fill_id"]):
                continue
            self._apply_fill(fill, now)
            self.store.mark_fill(fill["fill_id"], fill["ts"])
        live = {}
        for row in positions:
            pos = kalshi.parse_position(row)
            if pos:
                live[pos["ticker"]] = pos
        for st in self.assets.values():
            held = st.book.position
            if not held or held.paper:
                continue
            api = live.get(held.ticker)
            if api is None:
                self._journal_close(st, held, held.contracts, self._exit_bid(st, held), 0.0, now, "closed")
                st.book.position = None
            else:
                held.contracts = api["contracts"]
                held.side = api["side"]

    def _seed_positions(self, positions: list[dict], now: float) -> None:
        parsed = [p for p in (kalshi.parse_position(r) for r in positions) if p]
        for st in self.assets.values():
            if st.book.position and st.book.position.paper:
                continue
            series = st.meta["series"]
            match = next((p for p in parsed if str(p["ticker"]).startswith(series)), None)
            if not match:
                continue
            st.book.position = Position(
                asset=st.name,
                ticker=match["ticker"],
                side=match["side"],
                contracts=match["contracts"],
                entry=match["entry"],
                entry_ts=now,
                chop=None,
                fees=match["fees"],
                high_water=match["entry"] or 0.0,
            )

    def _apply_fill(self, fill: dict, now: float) -> None:
        st = self._asset_for(fill["ticker"])
        if st is None:
            return
        fee = fill["fee"]
        if fee is None and fill["price"] is not None:
            rate = float(self.cfg["fees"]["taker_rate"] if fill["is_taker"] else self.cfg["fees"]["maker_rate"])
            fee = fee_dollars(fill["contracts"], fill["price"], rate)
        fee = fee or 0.0
        pos = st.book.position
        if fill["action"] == "buy":
            if (
                pos
                and pos.ticker == fill["ticker"]
                and pos.side == fill["side"]
                and pos.entry is not None
                and fill["price"] is not None
            ):
                total = pos.contracts + fill["contracts"]
                pos.entry = (pos.entry * pos.contracts + fill["price"] * fill["contracts"]) / total
                pos.fees += fee
                pos.contracts = total
                return
            preview = self._preview(st, now, self._strategy(st.name))
            st.book.position = Position(
                asset=st.name,
                ticker=fill["ticker"],
                side=fill["side"],
                contracts=fill["contracts"],
                entry=fill["price"],
                entry_ts=fill["ts"],
                chop=preview["chop"]["score"],
                fees=fee,
                high_water=fill["price"] or 0.0,
            )
            self._mark_hour(st.name, fill["ts"])
            return
        if not pos or pos.ticker != fill["ticker"] or pos.side != fill["side"]:
            return
        sold = min(pos.contracts, fill["contracts"])
        self._journal_close(st, pos, sold, fill["price"], fee, now, "closed")
        remain = pos.contracts - sold
        if remain <= 1e-6:
            st.book.position = None
        else:
            pos.fees = pos.fees * (remain / pos.contracts) if pos.contracts else 0.0
            pos.contracts = remain

    def _journal_close(self, st, pos: Position, sold: float, exit_px: float | None, exit_fee: float, now: float, mode: str) -> None:
        entry_fee = 0.0 if pos.contracts <= 0 else pos.fees * (sold / pos.contracts)
        if pos.entry is None or exit_px is None:
            pnl = None
        else:
            pnl = (exit_px - pos.entry) * sold - entry_fee - exit_fee
        ref = self._ref(st, now)
        strike = st.book.strike
        if ref is None or strike is None:
            right = None
        elif pos.side == "YES":
            right = ref >= strike
        else:
            right = ref < strike
        self.store.add_journal(
            {
                "ts": now,
                "asset": pos.asset,
                "side": pos.side,
                "entry": pos.entry,
                "exit": exit_px,
                "contracts": sold,
                "net_pnl": pnl,
                "right": right,
                "mode": mode,
                "chop": pos.chop,
                "ticker": pos.ticker,
            }
        )
        if pos.paper:
            up_won = None if ref is None or strike is None else ref >= strike
            self.store.settle_paper_trade(
                pos.asset,
                pos.ticker,
                pos.side,
                up_won=up_won,
                net_pnl=pnl,
                right=right,
            )

    def _exit_bid(self, st: AssetRT, pos: Position) -> float | None:
        if pos.side == "YES":
            return st.book.yes_bid
        return st.book.no_bid

    def _asset_for(self, ticker: str) -> AssetRT | None:
        for st in self.assets.values():
            if ticker.startswith(st.meta["series"]):
                return st
        return None

    def _mark_hour(self, asset: str, ts: float) -> None:
        key = self._hour_key(asset, ts)
        current = list(self.store.settings().get("hour_entries") or [])
        if key not in current:
            current.append(key)
        self.store.save_setting("hour_entries", current[-96:])

    def _already_entered_hour(self, asset: str, now: float) -> bool:
        key = self._hour_key(asset, now)
        return key in (self.store.settings().get("hour_entries") or [])

    def _hour_key(self, asset: str, ts: float) -> str:
        stamp = datetime.fromtimestamp(ts, timezone.utc).strftime("%Y-%m-%dT%H")
        return f"{asset}:{stamp}"

    def _params_for(self, strategy_id: str, asset: str, saved: dict | None = None) -> dict:
        saved = saved if saved is not None else self.store.settings()
        shared = merge_shared_params(asset, saved.get(shared_settings_key(asset)))
        strat = merge_params(strategy_id, asset, saved.get(settings_key(strategy_id, asset)))
        return {**shared, **strat}

    def _strategy(self, asset: str = "BTC") -> dict:
        saved = self.store.settings()
        sid = saved.get("active") or "gates_15m"
        if sid not in self.cfg["strategies"]:
            sid = "gates_15m"
        spec = copy.deepcopy(self.cfg["strategies"][sid])
        spec["params"] = self._params_for(sid, asset, saved)
        spec["id"] = sid
        return spec

    def _apply_pending_params(self, asset: str) -> None:
        saved = self.store.settings()
        for sid in self.cfg["strategies"]:
            pk = pending_key(sid, asset)
            pending = saved.get(pk)
            if not pending:
                continue
            sk = settings_key(sid, asset)
            self.store.save_setting(sk, pending)
            self.store.save_setting(pk, None)

    def _position_open(self, st: AssetRT) -> bool:
        pos = st.book.position
        ticker = st.book.ticker or (st.market or {}).get("ticker")
        return bool(pos and ticker and pos.ticker == ticker)

    def _sol_confirm_secs(self, st: AssetRT, now: float, strategy: dict) -> float | None:
        if strategy.get("kind") != "sol" or st.name != "SOL":
            return None
        if st.sol_confirm_since is None:
            return 0.0
        return max(0.0, now - st.sol_confirm_since)

    def _weekend_signal_secs(self, st: AssetRT, now: float, strategy: dict) -> float | None:
        if strategy.get("kind") != "weekend_money":
            return None
        if st.weekend_hold_since is None:
            return 0.0
        return max(0.0, now - st.weekend_hold_since)

    def _tick_weekend_hold(self, st: AssetRT, now: float, strategy: dict, metrics: dict) -> None:
        if strategy.get("kind") != "weekend_money":
            st.weekend_hold_side = None
            st.weekend_hold_since = None
            return
        price = metrics.get("composite")
        probe = self._weekend_probe_gates(st, now, strategy, metrics, signal_hold_secs=0.0)
        if not probe:
            st.weekend_hold_side = None
            st.weekend_hold_since = None
            return
        favored, up_ready, down_ready = probe
        ready = (favored == "UP" and up_ready) or (favored == "DOWN" and down_ready)
        if not ready:
            st.weekend_hold_side = None
            st.weekend_hold_since = None
            return
        if st.weekend_hold_side != favored:
            st.weekend_hold_side = favored
            st.weekend_hold_since = now

    def _weekend_probe_gates(
        self, st: AssetRT, now: float, strategy: dict, metrics: dict, *, signal_hold_secs: float
    ) -> tuple[str, bool, bool] | None:
        from desk.engine.strategies import gate_sides
        from desk.engine.model import fee_dollars

        market = self._market_view(st)
        strike = market.get("strike")
        close_ts = market.get("close_ts")
        secs_left = None if close_ts is None else close_ts - now
        ref = metrics["index"] if metrics.get("index") is not None else metrics.get("composite")
        lag = None
        if metrics.get("composite") is not None and metrics.get("index") is not None:
            lag = metrics["composite"] - metrics["index"]
        move = metrics.get("move_1m") or 0.0
        p_up = sigma_t = None
        if ref is not None and strike is not None and secs_left is not None:
            from desk.engine.model import fair_up

            p_up, sigma_t, _ = fair_up(ref, strike, move, secs_left, self.cfg["model"])
        rate = float(self.cfg["fees"]["taker_rate"])
        params = self._params_for(strategy["id"], st.name)

        def fee_one(price: float) -> float:
            return fee_dollars(1, price, rate)

        wk_prefs = load_weekend_prefs(self.store.settings())
        wk_flag = is_weekend(now, wk_prefs["timezone"])
        chop_score = 0.0
        gates = gate_sides(
            strategy,
            asset=st.name,
            secs_left=secs_left,
            yes_bid=market.get("yes_bid"),
            yes_ask=market.get("yes_ask"),
            no_bid=market.get("no_bid"),
            no_ask=market.get("no_ask"),
            p_up=p_up,
            buy_pct=metrics.get("buy_pct"),
            momentum=metrics.get("momentum"),
            vol_ratio=(metrics.get("move_1m") or 0) / metrics["baseline_move"]
            if metrics.get("baseline_move")
            else None,
            now=now,
            fee_fn=fee_one,
            params=params,
            sigma_t=sigma_t if sigma_t and sigma_t > 0 else None,
            ref=ref,
            strike=strike,
            dual_feed_ok=metrics.get("dual_feed_ok", False),
            feed_detail=metrics.get("feed_detail", ""),
            composite_pct_move_3s=metrics.get("composite_pct_move_3s"),
            kalshi_mid_move_3s=metrics.get("kalshi_mid_move_3s"),
            index_ok=metrics.get("index") is not None,
            lag=lag,
            momentum_30=metrics.get("momentum_30"),
            momentum_60=metrics.get("momentum_60"),
            signal_hold_secs=signal_hold_secs,
            is_weekend=wk_flag,
            composite=metrics.get("composite"),
            index_price=metrics.get("index"),
            chop_log_show_row=bool(load_chop_gates(self.store.settings()).get("show_log_row", True)),
            chop_log_threshold=float(load_chop_gates(self.store.settings()).get("log_threshold", 30)),
            chop_log_basis=str(load_chop_gates(self.store.settings()).get("log_basis", "original")),
            chop_score_original=chop_score,
            chop_score_adjusted=None,
            paper_enabled=True,
            weekend_bump_cents=weekend_bump_for_params(params, is_weekend_flag=wk_flag),
            taker_rate=rate,
            g3_settlement_enabled=bool(wk_prefs.get("g3_settlement_enabled", True)),
            g4_cost_adjusted_enabled=bool(wk_prefs.get("g4_cost_adjusted_enabled", True)),
            g4_cost_pad_cents=float(wk_prefs.get("g4_cost_pad_cents", 0.5)),
        )

        def ready(side: str) -> bool:
            checks = checks_excluding_labels(gates.get(side, []), "Signal hold")
            return all_active_pass(checks)

        edge_up = edge_down = None
        if p_up is not None:
            from desk.engine.gates_eval import net_edge

            ys = (
                None
                if market.get("yes_ask") is None or market.get("yes_bid") is None
                else market["yes_ask"] - market["yes_bid"]
            )
            ns = (
                None
                if market.get("no_ask") is None or market.get("no_bid") is None
                else market["no_ask"] - market["no_bid"]
            )
            edge_up = net_edge(p_up, market.get("yes_ask"), ys, fee_one)
            edge_down = net_edge(1 - p_up, market.get("no_ask"), ns, fee_one)
        if edge_down is not None and (edge_up is None or edge_down > edge_up):
            favored = "DOWN"
        elif edge_up is not None:
            favored = "UP"
        else:
            return None
        return favored, ready("UP"), ready("DOWN")

    def _dual_feed(self, st: AssetRT, now: float) -> tuple[bool, str]:
        max_age = gate_locked.COMPOSITE_MAX_AGE
        parts = []
        ok_cb = ok_kr = False
        if st.coinbase:
            age = now - st.coinbase[1]
            ok_cb = age <= max_age
            parts.append(f"CB {age:.1f}s")
        else:
            parts.append("CB missing")
        if st.kraken:
            age = now - st.kraken[1]
            ok_kr = age <= max_age
            parts.append(f"KR {age:.1f}s")
        else:
            parts.append("KR missing")
        return ok_cb and ok_kr, " · ".join(parts)

    def _pct_move_3s(self, st: AssetRT, now: float, price: float | None) -> float | None:
        if price is None or not st.samples:
            return None
        target = now - gate_locked.ARB_STALE_LOOKBACK
        prior = None
        for ts, px in st.samples:
            if ts <= target:
                prior = px
        if prior is None or prior <= 0:
            return None
        return abs(price - prior) / prior

    def _mid_move_3s(self, st: AssetRT, now: float) -> float | None:
        if len(st.mid_history) < 2:
            return None
        recent = st.mid_history[-1][1]
        target = now - gate_locked.ARB_STALE_LOOKBACK
        old = None
        for ts, mid in st.mid_history:
            if ts <= target:
                old = mid
        if old is None:
            return None
        return recent - old

    def _market_view(self, st: AssetRT) -> dict:
        market = dict(st.market or {})
        market["ticker"] = st.book.ticker or market.get("ticker")
        market["strike"] = st.book.strike
        market["yes_bid"] = st.book.yes_bid
        market["yes_ask"] = st.book.yes_ask
        market["no_bid"] = st.book.no_bid
        market["no_ask"] = st.book.no_ask
        market["series"] = st.meta["series"]
        return market

    def _composite(self, st: AssetRT, now: float) -> tuple[float | None, list[str], float | None]:
        stale = float(self.cfg["feeds"]["stale_secs"])
        feeds = []
        if st.coinbase:
            feeds.append(("coinbase", st.coinbase[0], st.coinbase[1]))
        if st.kraken:
            feeds.append(("kraken", st.kraken[0], st.kraken[1]))
        price, names = composite_price(feeds, now, stale)
        ages = [now - ts for name, _, ts in feeds if name in names]
        return price, names, (max(ages) if ages else None)

    def _ref(self, st: AssetRT, now: float) -> float | None:
        index = self._fresh_index(st, now)
        if index is not None:
            return index
        price, _, _ = self._composite(st, now)
        return price

    def _fresh_index(self, st: AssetRT, now: float) -> float | None:
        stale = float(self.cfg["feeds"]["stale_secs"])
        if st.index and st.index[0] > 0 and now - st.index[1] <= stale:
            return st.index[0]
        return None

    def _metrics(self, st: AssetRT, now: float) -> dict:
        price, names, age = self._composite(st, now)
        feed_ages = {}
        if st.coinbase:
            feed_ages["coinbase"] = round(now - st.coinbase[1], 2)
        if st.kraken:
            feed_ages["kraken"] = round(now - st.kraken[1], 2)
        window = float(self.cfg["feeds"]["vol_window_secs"])
        base_window = float(self.cfg["feeds"]["baseline_window_secs"])
        samples = list(st.samples)
        move = move_1m_from_returns(log_return_stdev(samples, now, window), price)
        baseline = move_1m_from_returns(log_return_stdev(samples, now, base_window), price)
        dual_ok, dual_detail = self._dual_feed(st, now)
        sid = self._strategy(st.name)["id"]
        return {
            "composite": price,
            "composite_age": age,
            "feed_ages": feed_ages,
            "feeds": names,
            "index": self._fresh_index(st, now),
            "move_1m": move,
            "baseline_move": baseline,
            "buy_pct": self._buy_pct(st, now),
            "momentum": self._momentum(st, now, price),
            "momentum_30": self._momentum_secs(st, now, price, 30),
            "momentum_60": self._momentum_secs(st, now, price, 60),
            "crossings": st.book.crossings,
            "dual_feed_ok": dual_ok,
            "feed_detail": dual_detail,
            "composite_pct_move_3s": self._pct_move_3s(st, now, price),
            "kalshi_mid_move_3s": self._mid_move_3s(st, now),
            "tunable_params": self._params_for(sid, st.name),
        }

    def _buy_pct(self, st: AssetRT, now: float) -> float | None:
        window = float(self.cfg["feeds"]["flow_window_secs"])
        buy = sell = 0.0
        for ts, usd, is_buy in st.trades:
            if now - window <= ts <= now:
                if is_buy:
                    buy += usd
                else:
                    sell += usd
        total = buy + sell
        if total <= 0:
            return None
        return buy / total * 100.0

    def _momentum_secs(self, st: AssetRT, now: float, price: float | None, window: float) -> int | None:
        if price is None or not st.samples:
            return None
        if now - st.samples[0][0] < window - 1:
            return None
        target = now - window
        prior = None
        for ts, px in st.samples:
            if ts <= target:
                prior = px
            else:
                break
        if prior is None:
            return None
        if price > prior:
            return 1
        if price < prior:
            return -1
        return 0

    def _momentum(self, st: AssetRT, now: float, price: float | None) -> int | None:
        window = float(self.cfg["feeds"]["momentum_window_secs"])
        return self._momentum_secs(st, now, price, window)

    def update_measurement_prefs(self, **kwargs) -> dict:
        prefs = load_measurement_prefs(self.store.settings())
        for key in prefs:
            if key in kwargs and kwargs[key] is not None:
                prefs[key] = bool(kwargs[key])
        self.store.save_setting(MEASUREMENT_PREFS_KEY, prefs)
        for st in self.assets.values():
            st.meas_liq.enabled = bool(prefs.get("liquidation"))
        return {"ok": True, "state": self.snapshot()}

    def update_chop_gates(
        self,
        *,
        log_threshold: float | None = None,
        log_basis: str | None = None,
        show_log_row: bool | None = None,
        soft_enabled: bool | None = None,
        tier_low_max: float | None = None,
        tier_mid_max: float | None = None,
        addon_below_low_cents: float | None = None,
        addon_mid_cents: float | None = None,
        reset_soft_defaults: bool | None = None,
    ) -> dict:
        prefs = load_chop_gates(self.store.settings())
        if reset_soft_defaults:
            prefs.update(reset_chop_soft_defaults())
        if log_threshold is not None:
            prefs["log_threshold"] = float(log_threshold)
        if log_basis is not None:
            prefs["log_basis"] = log_basis if log_basis in ("original", "adjusted") else prefs["log_basis"]
        if show_log_row is not None:
            prefs["show_log_row"] = bool(show_log_row)
        if soft_enabled is not None:
            prefs["soft_enabled"] = bool(soft_enabled)
        if tier_low_max is not None:
            prefs["tier_low_max"] = float(tier_low_max)
        if tier_mid_max is not None:
            prefs["tier_mid_max"] = float(tier_mid_max)
        if addon_below_low_cents is not None:
            prefs["addon_below_low_cents"] = float(addon_below_low_cents)
        if addon_mid_cents is not None:
            prefs["addon_mid_cents"] = float(addon_mid_cents)
        prefs = load_chop_gates({CHOP_GATES_KEY: prefs})
        self.store.save_setting(CHOP_GATES_KEY, prefs)
        return {"ok": True, "state": self.snapshot()}

    def update_weekend_prefs(
        self,
        *,
        timezone: str | None = None,
        feed_freshness_enabled: bool | None = None,
        feed_max_age_secs: float | None = None,
    ) -> dict:
        prefs = load_weekend_prefs(self.store.settings())
        if timezone is not None:
            prefs["timezone"] = timezone if timezone in ("America/New_York", "UTC") else prefs["timezone"]
        if feed_freshness_enabled is not None:
            prefs["feed_freshness_enabled"] = bool(feed_freshness_enabled)
        if feed_max_age_secs is not None:
            prefs["feed_max_age_secs"] = max(0.5, min(10.0, float(feed_max_age_secs)))
        self.store.save_setting(WEEKEND_PREFS_KEY, prefs)
        return {"ok": True, "state": self.snapshot()}

    def update_paper_modes(
        self,
        *,
        edge_basis: str | None = None,
        min_net_edge_cents: float | None = None,
        ignore_edge_gate: bool | None = None,
        fade_model: bool | None = None,
        fade_trigger_cents: float | None = None,
        momentum_gate_enabled: bool | None = None,
    ) -> dict:
        modes = load_paper_modes(self.store.settings())
        if edge_basis is not None:
            modes["edge_basis"] = edge_basis if edge_basis in ("net", "entry") else "net"
        if min_net_edge_cents is not None:
            modes["min_net_edge_cents"] = max(-10.0, min(10.0, float(min_net_edge_cents)))
        if ignore_edge_gate is not None:
            modes["ignore_edge_gate"] = bool(ignore_edge_gate)
        if fade_model is not None:
            modes["fade_model"] = bool(fade_model)
        if fade_trigger_cents is not None:
            modes["fade_trigger_cents"] = max(1.0, min(30.0, float(fade_trigger_cents)))
        if momentum_gate_enabled is not None:
            modes["momentum_gate_enabled"] = bool(momentum_gate_enabled)
        self.store.save_setting(PAPER_SETTINGS_KEY, modes)
        return {"ok": True, "state": self.snapshot()}

    def update_setting(
        self,
        active: str | None,
        strategy: str | None,
        key: str | None,
        value: float | None,
        asset: str | None = None,
        paper_edge_basis: str | None = None,
        paper_min_net_edge_cents: float | None = None,
        paper_ignore_edge_gate: bool | None = None,
        paper_fade_model: bool | None = None,
        paper_fade_trigger_cents: float | None = None,
        weekend_timezone: str | None = None,
        weekend_feed_freshness_enabled: bool | None = None,
        weekend_feed_max_age_secs: float | None = None,
        paper_momentum_gate_enabled: bool | None = None,
        meas_settlement_window: bool | None = None,
        meas_book_metrics: bool | None = None,
        meas_window_features: bool | None = None,
        meas_liquidation: bool | None = None,
        meas_price_buckets: bool | None = None,
        chop_log_threshold: float | None = None,
        chop_log_basis: str | None = None,
        chop_show_log_row: bool | None = None,
        chop_soft_enabled: bool | None = None,
        chop_tier_low_max: float | None = None,
        chop_tier_mid_max: float | None = None,
        chop_addon_below_low_cents: float | None = None,
        chop_addon_mid_cents: float | None = None,
        chop_reset_soft_defaults: bool | None = None,
    ) -> dict:
        now = time.time()
        if any(
            x is not None
            for x in (
                chop_log_threshold,
                chop_log_basis,
                chop_show_log_row,
                chop_soft_enabled,
                chop_tier_low_max,
                chop_tier_mid_max,
                chop_addon_below_low_cents,
                chop_addon_mid_cents,
                chop_reset_soft_defaults,
            )
        ):
            return self.update_chop_gates(
                log_threshold=chop_log_threshold,
                log_basis=chop_log_basis,
                show_log_row=chop_show_log_row,
                soft_enabled=chop_soft_enabled,
                tier_low_max=chop_tier_low_max,
                tier_mid_max=chop_tier_mid_max,
                addon_below_low_cents=chop_addon_below_low_cents,
                addon_mid_cents=chop_addon_mid_cents,
                reset_soft_defaults=chop_reset_soft_defaults,
            )
        if any(
            x is not None
            for x in (
                meas_settlement_window,
                meas_book_metrics,
                meas_window_features,
                meas_liquidation,
                meas_price_buckets,
            )
        ):
            return self.update_measurement_prefs(
                settlement_window=meas_settlement_window,
                book_metrics=meas_book_metrics,
                window_features=meas_window_features,
                liquidation=meas_liquidation,
                price_buckets=meas_price_buckets,
            )
        if any(
            x is not None
            for x in (
                weekend_timezone,
                weekend_feed_freshness_enabled,
                weekend_feed_max_age_secs,
            )
        ):
            return self.update_weekend_prefs(
                timezone=weekend_timezone,
                feed_freshness_enabled=weekend_feed_freshness_enabled,
                feed_max_age_secs=weekend_feed_max_age_secs,
            )
        if any(
            x is not None
            for x in (
                paper_edge_basis,
                paper_min_net_edge_cents,
                paper_ignore_edge_gate,
                paper_fade_model,
                paper_fade_trigger_cents,
                paper_momentum_gate_enabled,
            )
        ):
            return self.update_paper_modes(
                edge_basis=paper_edge_basis,
                min_net_edge_cents=paper_min_net_edge_cents,
                ignore_edge_gate=paper_ignore_edge_gate,
                fade_model=paper_fade_model,
                fade_trigger_cents=paper_fade_trigger_cents,
                momentum_gate_enabled=paper_momentum_gate_enabled,
            )
        if strategy == "shared" and key is not None and value is not None:
            if not asset or asset not in self.assets:
                return {"ok": False, "error": "asset required"}
            try:
                num = clamp_shared_param(asset, key, float(value))
            except KeyError:
                return {"ok": False, "error": "unknown shared param"}
            sk = shared_settings_key(asset)
            saved = self.store.settings()
            current = dict(saved.get(sk) or merge_shared_params(asset, None))
            current[key] = num
            self.store.save_setting(sk, current)
            return {"ok": True, "state": self.snapshot()}
        if active:
            if active not in self.cfg["strategies"]:
                return {"ok": False, "error": "unknown strategy"}
            self.store.save_setting("active", active)
        if strategy and key is not None and value is not None:
            if not asset or asset not in self.assets:
                return {"ok": False, "error": "asset required"}
            sliders = slider_defs(strategy, asset)
            slider = next((s for s in sliders if s["key"] == key), None)
            if slider is None:
                return {"ok": False, "error": "unknown slider"}
            try:
                num = clamp_param(asset, key, float(value))
            except KeyError:
                return {"ok": False, "error": "unknown param"}
            sk = settings_key(strategy, asset)
            saved = self.store.settings()
            current = dict(saved.get(sk) or {})
            old = current.get(key)
            if old is not None and abs(float(old) - num) < 1e-9:
                return {"ok": True, "state": self.snapshot()}
            current[key] = num
            st = self.assets[asset]
            pending = self._position_open(st)
            if pending:
                pk = pending_key(strategy, asset)
                pend = dict(saved.get(pk) or self._params_for(strategy, asset, saved))
                pend[key] = num
                self.store.save_setting(pk, pend)
                self.store.add_param_change(
                    ts=now,
                    asset=asset,
                    strategy=strategy,
                    param=key,
                    old_value=old,
                    new_value=num,
                    pending=True,
                )
            else:
                self.store.save_setting(sk, current)
                self.store.add_param_change(
                    ts=now,
                    asset=asset,
                    strategy=strategy,
                    param=key,
                    old_value=old,
                    new_value=num,
                    pending=False,
                )
        return {"ok": True, "state": self.snapshot()}

    def reset_settings(self) -> dict:
        from desk.engine.tunable import all_defaults_for_reset

        now = time.time()
        saved = self.store.settings()
        for combo, params in all_defaults_for_reset().items():
            sid, ast = combo.split(":", 1)
            sk = settings_key(sid, ast)
            old = saved.get(sk)
            self.store.save_setting(sk, params)
            self.store.save_setting(pending_key(sid, ast), None)
            for k, v in params.items():
                self.store.add_param_change(
                    ts=now,
                    asset=ast,
                    strategy=sid,
                    param=k,
                    old_value=(old or {}).get(k) if isinstance(old, dict) else None,
                    new_value=v,
                    pending=False,
                )
        self.store.save_setting("active", "gates_15m")
        return {"ok": True, "state": self.snapshot()}

    def clear_journal(self) -> dict:
        self.store.clear_journal()
        return {"ok": True}
