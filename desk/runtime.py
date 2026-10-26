"""One-second desk loop. Paper trades at live quotes; never sends Kalshi orders."""
from __future__ import annotations

import asyncio
import copy
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from kalshi_auth import load_private_key_from_env

from desk.engine.load import load_config
from desk.engine.model import composite_price, fee_dollars, log_return_stdev, move_1m_from_returns  # fee_dollars used for paper exits
from desk.engine.rollover import Book, Position, _auto_settle, rollover
from desk.engine.paper import can_paper_enter, paper_buy, side_to_yes
from desk.engine.strategies import all_pass
from desk.engine.view import build_asset, et_stamp, journal_stats, stamp_rows
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

    def __post_init__(self) -> None:
        self.book.asset = self.name


class Desk:
    def __init__(self, store_path: Path | None = None):
        self.cfg = load_config()
        self.store = Store(store_path or ROOT / "desk.sqlite")
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
                        for key in ("yes_bid", "yes_ask", "no_bid", "no_ask"):
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
                async with self._lock:
                    now = time.time()
                    for name, price in indexes.items():
                        if price and price > 0:
                            self.assets[name].index = (price, now)
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
            await asyncio.sleep(2)

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

    def _payload(self, now: float) -> dict:
        strategy = self._strategy()
        assets = {}
        for name, st in self.assets.items():
            metrics = self._metrics(st, now)
            market = self._market_view(st)
            built = build_asset(
                asset=name,
                now=now,
                cfg=self.cfg,
                strategy=strategy,
                market=market,
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
                already_entered_hour=self._already_entered_hour(name, now),
                paper_buys=self._paper_buys(st),
            )
            built["bot"]["feed_ages"] = metrics["feed_ages"]
            built["market"]["expired"] = bool((st.market or {}).get("expired")) or (
                built["tab"]["secs_left"] is not None and built["tab"]["secs_left"] < 0
            )
            assets[name] = built
        rows = self.store.journal()
        strategies = []
        saved = self.store.settings()
        for sid, spec in self.cfg["strategies"].items():
            params = dict(spec["params"])
            params.update(saved.get(f"params:{sid}") or {})
            strategies.append(
                {
                    "id": sid,
                    "label": spec["label"],
                    "kind": spec["kind"],
                    "log_only": bool(spec.get("log_only")),
                    "params": params,
                    "sliders": spec["sliders"],
                }
            )
        return {
            "now": now,
            "et": et_stamp(now),
            "authed": self.authed,
            "auth_note": self.auth_note,
            "observe_only": not bool((self.cfg.get("paper") or {}).get("enabled")),
            "paper": self.cfg.get("paper") or {},
            "active": strategy["id"],
            "strategies": strategies,
            "asset_order": list(self.assets),
            "assets": assets,
            "journal": {"stats": journal_stats(rows), "rows": stamp_rows(rows)},
            "scanner": stamp_rows(self.store.scans()),
            "paper_orders": stamp_rows(self.store.paper_orders()),
            "rules": self.cfg["suggest"],
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
            self._run_paper(st, now)
            self._maybe_scan(st, now)

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
        strategy = self._strategy()
        ticker = st.book.ticker or ""
        if not ticker:
            return
        buys = self._paper_buys(st)
        view = self._preview(st, now, strategy, buys)
        view["_strategy"] = strategy
        pos = st.book.position
        rate = float(self.cfg["fees"]["taker_rate"])
        paper_cfg = self.cfg.get("paper") or {}
        max_e = int(paper_cfg.get("max_entries_per_market", 2))
        cooldown = float(paper_cfg.get("entry_cooldown_secs", 30))
        cooldown_ok = now - st.last_paper_entry >= cooldown

        if pos and pos.paper and pos.ticker == ticker:
            action = view["suggestion"]["action"]
            if action == "EXIT NOW":
                self._paper_close(st, pos, now, rate)
                return
            if action == "REVERSE":
                old = pos.side
                self._paper_close(st, pos, now, rate)
                buys = self._paper_buys(st)
                other = "DOWN" if old == "YES" else "UP"
                view = self._preview(st, now, strategy, buys)
                if buys < max_e and cooldown_ok and all_pass((view.get("gates") or {}).get(other) or []):
                    paper_buy(st=st, view=view, side=other, now=now, cfg=self.cfg, store=self.store, taker_rate=rate)
                    st.last_paper_entry = now
                return

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
        paper_buy(st=st, view=view, side=detail, now=now, cfg=self.cfg, store=self.store, taker_rate=rate)
        st.last_paper_entry = now

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
        strategy = self._strategy()
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

    def _preview(self, st: AssetRT, now: float, strategy: dict, paper_buys: int | None = None) -> dict:
        metrics = self._metrics(st, now)
        if paper_buys is None:
            paper_buys = self._paper_buys(st)
        return build_asset(
            asset=st.name,
            now=now,
            cfg=self.cfg,
            strategy=strategy,
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
        )

    def _apply_market(self, st: AssetRT, market: dict | None, now: float) -> None:
        if not market:
            self._expire(st, now)
            return
        if st.book.ticker and market["ticker"] != st.book.ticker:
            new_book, row = rollover(st.book, market["ticker"], self._ref(st, now))
            if row:
                row["ts"] = now
                self.store.add_journal(row)
                if book.position and book.position.paper:
                    self.store.clear_paper_open(st.name)
            st.book = new_book
            st.book.asset = st.name
        st.book.ticker = market["ticker"]
        st.book.asset = st.name
        st.book.strike = market.get("strike")
        for key in ("yes_bid", "yes_ask", "no_bid", "no_ask"):
            if market.get(key) is not None:
                setattr(st.book, key, market[key])
        st.market = market

    def _expire(self, st: AssetRT, now: float) -> None:
        close_ts = (st.market or {}).get("close_ts")
        if close_ts is None or now < close_ts:
            return
        pos = st.book.position
        if pos and pos.ticker == (st.book.ticker or st.market.get("ticker")):
            row = _auto_settle(pos, st.book.strike, self._ref(st, now))
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
            preview = self._preview(st, now, self._strategy())
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

    def _strategy(self) -> dict:
        saved = self.store.settings()
        sid = saved.get("active") or "gates_15m"
        if sid not in self.cfg["strategies"]:
            sid = "gates_15m"
        spec = copy.deepcopy(self.cfg["strategies"][sid])
        spec["params"].update(saved.get(f"params:{sid}") or {})
        spec["id"] = sid
        return spec

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
            "crossings": st.book.crossings,
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

    def _momentum(self, st: AssetRT, now: float, price: float | None) -> int | None:
        window = float(self.cfg["feeds"]["momentum_window_secs"])
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

    def update_setting(self, active: str | None, strategy: str | None, key: str | None, value: float | None) -> dict:
        if active:
            if active not in self.cfg["strategies"]:
                return {"ok": False, "error": "unknown strategy"}
            self.store.save_setting("active", active)
        if strategy and key is not None and value is not None:
            spec = self.cfg["strategies"].get(strategy)
            slider = None if not spec else next((s for s in spec["sliders"] if s["key"] == key), None)
            if slider is None:
                return {"ok": False, "error": "unknown slider"}
            num = min(float(slider["max"]), max(float(slider["min"]), float(value)))
            current = dict(self.store.settings().get(f"params:{strategy}") or {})
            current[key] = num
            self.store.save_setting(f"params:{strategy}", current)
        return {"ok": True, "state": self.snapshot()}

    def reset_settings(self) -> dict:
        self.store.clear_settings()
        return {"ok": True}

    def clear_journal(self) -> dict:
        self.store.clear_journal()
        return {"ok": True}
