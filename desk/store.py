"""SQLite journal, scanner log, and slider overrides."""
from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path


class Store:
    def __init__(self, path: str | Path):
        self.conn = sqlite3.connect(str(path), check_same_thread=False)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self._init()

    def _init(self) -> None:
        self.conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS journal (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                asset TEXT NOT NULL,
                side TEXT NOT NULL,
                entry REAL,
                exit_px REAL,
                contracts REAL,
                net_pnl REAL,
                right INTEGER,
                mode TEXT NOT NULL,
                chop REAL,
                ticker TEXT
            );
            CREATE TABLE IF NOT EXISTS scanner (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                asset TEXT NOT NULL,
                side TEXT NOT NULL,
                ask REAL,
                edge REAL
            );
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fills_seen (
                fill_id TEXT PRIMARY KEY,
                ts REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_buys (
                ticker TEXT PRIMARY KEY,
                count INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS paper_open (
                asset TEXT PRIMARY KEY,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                contracts REAL NOT NULL,
                entry REAL,
                entry_ts REAL NOT NULL,
                chop REAL,
                fees REAL NOT NULL,
                high_water REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS shadow_paper (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker TEXT NOT NULL,
                asset TEXT NOT NULL,
                side TEXT NOT NULL,
                entry_ts REAL NOT NULL,
                entry_ask REAL,
                p_up REAL,
                chop REAL,
                strike REAL,
                gates_json TEXT,
                settled INTEGER NOT NULL DEFAULT 0,
                settle_composite REAL,
                up_won INTEGER,
                right INTEGER,
                exit_px REAL,
                net_pnl REAL,
                settle_note TEXT,
                UNIQUE(ticker, side)
            );
            CREATE TABLE IF NOT EXISTS param_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                asset TEXT NOT NULL,
                strategy TEXT NOT NULL,
                param TEXT NOT NULL,
                old_value REAL,
                new_value REAL,
                pending INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS paper_orders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                asset TEXT NOT NULL,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                action TEXT NOT NULL,
                price REAL,
                contracts REAL,
                fee REAL,
                edge REAL,
                chop REAL
            );
            CREATE TABLE IF NOT EXISTS paper_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                asset TEXT NOT NULL,
                ticker TEXT NOT NULL,
                side TEXT NOT NULL,
                gate_mode TEXT NOT NULL,
                edge_net REAL,
                edge_entry REAL,
                raw_prob_edge REAL,
                edge_bucket TEXT,
                p_up REAL,
                ask REAL,
                fee REAL,
                spread REAL,
                secs_left REAL,
                settled INTEGER NOT NULL DEFAULT 0,
                up_won INTEGER,
                net_pnl REAL,
                right INTEGER
            );
            """
        )
        self.conn.commit()
        for ddl in (
            "ALTER TABLE paper_trades ADD COLUMN is_weekend INTEGER NOT NULL DEFAULT 0",
            "ALTER TABLE paper_trades ADD COLUMN weekend_bump_applied REAL NOT NULL DEFAULT 0",
            "ALTER TABLE paper_trades ADD COLUMN strategy TEXT",
            "ALTER TABLE paper_trades ADD COLUMN hour_et INTEGER",
            "ALTER TABLE paper_trades ADD COLUMN session TEXT",
            "ALTER TABLE paper_trades ADD COLUMN meas_json TEXT",
            """CREATE TABLE IF NOT EXISTS measurement_ticks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                asset TEXT NOT NULL,
                ticker TEXT,
                payload TEXT NOT NULL
            )""",
            """CREATE TABLE IF NOT EXISTS chop_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                asset TEXT NOT NULL,
                ticker TEXT NOT NULL,
                strategy TEXT,
                side TEXT NOT NULL,
                chop REAL,
                chop_partial INTEGER NOT NULL DEFAULT 0,
                missing_rows INTEGER NOT NULL DEFAULT 0,
                gate_layer_result TEXT NOT NULL,
                chop_addon_cents REAL NOT NULL DEFAULT 0,
                block_reason TEXT,
                would_have_entered INTEGER NOT NULL DEFAULT 0,
                taken INTEGER NOT NULL DEFAULT 0,
                entry_ask REAL,
                fee REAL,
                shadow_id INTEGER
            )""",
            """CREATE TABLE IF NOT EXISTS chop_shadow_trades (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                ts REAL NOT NULL,
                asset TEXT NOT NULL,
                ticker TEXT NOT NULL,
                strategy TEXT,
                side TEXT NOT NULL,
                entry_ask REAL,
                fee REAL,
                chop REAL,
                settled INTEGER NOT NULL DEFAULT 0,
                settle_composite REAL,
                up_won INTEGER,
                right INTEGER,
                exit_px REAL,
                net_pnl REAL,
                settle_note TEXT
            )""",
        ):
            try:
                self.conn.execute(ddl)
                self.conn.commit()
            except sqlite3.OperationalError:
                pass

    def seen_fill(self, fill_id: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM fills_seen WHERE fill_id = ?", (fill_id,)).fetchone()
        return row is not None

    def mark_fill(self, fill_id: str, ts: float | None = None) -> None:
        self.conn.execute(
            "INSERT OR IGNORE INTO fills_seen (fill_id, ts) VALUES (?, ?)",
            (fill_id, ts if ts is not None else time.time()),
        )
        self.conn.commit()

    def add_journal(self, row: dict) -> None:
        self.conn.execute(
            """
            INSERT INTO journal (ts, asset, side, entry, exit_px, contracts, net_pnl, right, mode, chop, ticker)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("ts", time.time()),
                row["asset"],
                row["side"],
                row.get("entry"),
                row.get("exit"),
                row.get("contracts"),
                row.get("net_pnl"),
                None if row.get("right") is None else int(bool(row["right"])),
                row.get("mode", "closed"),
                row.get("chop"),
                row.get("ticker"),
            ),
        )
        self.conn.commit()

    def journal(self, limit: int = 80) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM journal ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def clear_settings(self) -> None:
        self.conn.execute("DELETE FROM settings")
        self.conn.commit()

    def clear_journal(self) -> None:
        self.conn.execute("DELETE FROM param_changes")
        self.conn.execute("DELETE FROM journal")
        self.conn.execute("DELETE FROM scanner")
        self.conn.execute("DELETE FROM paper_buys")
        self.conn.execute("DELETE FROM paper_orders")
        self.conn.execute("DELETE FROM paper_trades")
        self.conn.execute("DELETE FROM measurement_ticks")
        self.conn.execute("DELETE FROM paper_open")
        self.conn.execute("DELETE FROM shadow_paper")
        self.conn.execute("DELETE FROM chop_candidates")
        self.conn.execute("DELETE FROM chop_shadow_trades")
        self.conn.commit()

    def shadow_try_insert(self, row: dict) -> bool:
        try:
            self.conn.execute(
                """
                INSERT INTO shadow_paper
                (ticker, asset, side, entry_ts, entry_ask, p_up, chop, strike, gates_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["ticker"],
                    row["asset"],
                    row["side"],
                    row["entry_ts"],
                    row.get("entry_ask"),
                    row.get("p_up"),
                    row.get("chop"),
                    row.get("strike"),
                    row.get("gates_json"),
                ),
            )
            self.conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False

    def shadow_unsettled(self, ticker: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM shadow_paper WHERE ticker = ? AND settled = 0",
            (ticker,),
        ).fetchall()
        return [dict(r) for r in rows]

    def shadow_settle_row(self, row_id: int, updates: dict) -> bool:
        """Apply settlement. Returns False if outcome missing (row stays open for retry)."""
        if updates.get("right") is None or updates.get("net_pnl") is None:
            return False
        self.conn.execute(
            """
            UPDATE shadow_paper SET
              settled = 1,
              settle_composite = ?,
              up_won = ?,
              right = ?,
              exit_px = ?,
              net_pnl = ?,
              settle_note = ?
            WHERE id = ?
            """,
            (
                updates.get("settle_composite"),
                updates.get("up_won"),
                updates.get("right"),
                updates.get("exit_px"),
                updates.get("net_pnl"),
                updates.get("settle_note"),
                row_id,
            ),
        )
        self.conn.commit()
        return True

    def shadow_reset_invalid_settlements(self) -> int:
        """Drop rows that were marked settled without a scored outcome (unrecoverable)."""
        cur = self.conn.execute(
            """
            DELETE FROM shadow_paper
            WHERE settled = 1 AND right IS NULL AND net_pnl IS NULL
            """
        )
        self.conn.commit()
        return cur.rowcount

    def shadow_purge_stale_open(self, before_ts: float) -> int:
        """Remove open shadow rows from windows that ended before before_ts."""
        cur = self.conn.execute(
            "DELETE FROM shadow_paper WHERE settled = 0 AND entry_ts < ?",
            (before_ts,),
        )
        self.conn.commit()
        return cur.rowcount

    def shadow_all(self, limit: int = 120) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM shadow_paper ORDER BY entry_ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_chop_candidate(self, row: dict) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO chop_candidates (
              ts, asset, ticker, strategy, side, chop, chop_partial, missing_rows,
              gate_layer_result, chop_addon_cents, block_reason, would_have_entered,
              taken, entry_ask, fee, shadow_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("ts", time.time()),
                row["asset"],
                row["ticker"],
                row.get("strategy"),
                row["side"],
                row.get("chop"),
                1 if row.get("chop_partial") else 0,
                int(row.get("missing_rows") or 0),
                row["gate_layer_result"],
                float(row.get("chop_addon_cents") or 0),
                row.get("block_reason"),
                1 if row.get("would_have_entered") else 0,
                1 if row.get("taken") else 0,
                row.get("entry_ask"),
                row.get("fee"),
                row.get("shadow_id"),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def chop_candidates(self, limit: int = 2000) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM chop_candidates ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def add_chop_shadow(self, row: dict) -> int:
        cur = self.conn.execute(
            """
            INSERT INTO chop_shadow_trades
            (ts, asset, ticker, strategy, side, entry_ask, fee, chop)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("ts", time.time()),
                row["asset"],
                row["ticker"],
                row.get("strategy"),
                row["side"],
                row.get("entry_ask"),
                row.get("fee"),
                row.get("chop"),
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def chop_shadow_unsettled(self, ticker: str) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM chop_shadow_trades WHERE ticker = ? AND settled = 0",
            (ticker,),
        ).fetchall()
        return [dict(r) for r in rows]

    def chop_shadow_settle_row(self, row_id: int, updates: dict) -> bool:
        if updates.get("right") is None or updates.get("net_pnl") is None:
            return False
        self.conn.execute(
            """
            UPDATE chop_shadow_trades SET
              settled = 1,
              settle_composite = ?,
              up_won = ?,
              right = ?,
              exit_px = ?,
              net_pnl = ?,
              settle_note = ?
            WHERE id = ?
            """,
            (
                updates.get("settle_composite"),
                updates.get("up_won"),
                updates.get("right"),
                updates.get("exit_px"),
                updates.get("net_pnl"),
                updates.get("settle_note"),
                row_id,
            ),
        )
        self.conn.commit()
        return True

    def chop_shadow_all(self, limit: int = 500) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM chop_shadow_trades ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def chop_shadow_purge_stale(self, before_ts: float) -> int:
        cur = self.conn.execute(
            "DELETE FROM chop_shadow_trades WHERE settled = 0 AND ts < ?",
            (before_ts,),
        )
        self.conn.commit()
        return cur.rowcount

    def paper_buy_count(self, ticker: str) -> int:
        row = self.conn.execute("SELECT count FROM paper_buys WHERE ticker = ?", (ticker,)).fetchone()
        return int(row["count"]) if row else 0

    def record_paper_buy(self, ticker: str) -> None:
        n = self.paper_buy_count(ticker) + 1
        self.conn.execute(
            "INSERT INTO paper_buys (ticker, count) VALUES (?, ?) ON CONFLICT(ticker) DO UPDATE SET count = excluded.count",
            (ticker, n),
        )
        self.conn.commit()

    def add_paper_order(self, **row) -> None:
        self.conn.execute(
            """
            INSERT INTO paper_orders (ts, asset, ticker, side, action, price, contracts, fee, edge, chop)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("ts", time.time()),
                row["asset"],
                row["ticker"],
                row["side"],
                row["action"],
                row.get("price"),
                row.get("contracts"),
                row.get("fee"),
                row.get("edge"),
                row.get("chop"),
            ),
        )
        self.conn.commit()

    def add_paper_trade(self, **row) -> None:
        from desk.engine.edge_modes import edge_bucket_cents

        bucket = edge_bucket_cents(row.get("edge_net"))
        self.conn.execute(
            """
            INSERT INTO paper_trades (
              ts, asset, ticker, side, gate_mode, edge_net, edge_entry, raw_prob_edge,
              edge_bucket, p_up, ask, fee, spread, secs_left, is_weekend, weekend_bump_applied,
              strategy, hour_et, session, meas_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row.get("ts", time.time()),
                row["asset"],
                row["ticker"],
                row["side"],
                row.get("gate_mode", "normal"),
                row.get("edge_net"),
                row.get("edge_entry"),
                row.get("raw_prob_edge"),
                bucket,
                row.get("p_up"),
                row.get("ask"),
                row.get("fee"),
                row.get("spread"),
                row.get("secs_left"),
                1 if row.get("is_weekend") else 0,
                float(row.get("weekend_bump_applied") or 0),
                row.get("strategy"),
                row.get("hour_et"),
                row.get("session"),
                json.dumps(row.get("meas_json")) if row.get("meas_json") is not None else None,
            ),
        )
        self.conn.commit()

    def add_measurement_tick(self, *, ts: float, asset: str, ticker: str | None, payload: dict) -> None:
        self.conn.execute(
            "INSERT INTO measurement_ticks (ts, asset, ticker, payload) VALUES (?, ?, ?, ?)",
            (ts, asset, ticker, json.dumps(payload)),
        )
        self.conn.commit()

    def measurement_ticks(self, limit: int = 100) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM measurement_ticks ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        out = []
        for r in rows:
            item = dict(r)
            try:
                item["payload"] = json.loads(item["payload"])
            except (TypeError, json.JSONDecodeError):
                pass
            out.append(item)
        return out

    def settle_paper_trade(self, asset: str, ticker: str, side: str, *, up_won: bool | None, net_pnl: float | None, right: bool | None) -> None:
        self.conn.execute(
            """
            UPDATE paper_trades SET settled = 1, up_won = ?, net_pnl = ?, right = ?
            WHERE asset = ? AND ticker = ? AND side = ? AND settled = 0
            """,
            (
                None if up_won is None else int(bool(up_won)),
                net_pnl,
                None if right is None else int(bool(right)),
                asset,
                ticker,
                side,
            ),
        )
        self.conn.commit()

    def paper_trades(self, limit: int = 500) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM paper_trades ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def paper_orders(self, limit: int = 40) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM paper_orders ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_paper_open(self, asset: str, pos) -> None:
        self.conn.execute(
            """
            INSERT INTO paper_open (asset, ticker, side, contracts, entry, entry_ts, chop, fees, high_water)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(asset) DO UPDATE SET
              ticker=excluded.ticker, side=excluded.side, contracts=excluded.contracts,
              entry=excluded.entry, entry_ts=excluded.entry_ts, chop=excluded.chop,
              fees=excluded.fees, high_water=excluded.high_water
            """,
            (
                asset,
                pos.ticker,
                pos.side,
                pos.contracts,
                pos.entry,
                pos.entry_ts,
                pos.chop,
                pos.fees,
                pos.high_water,
            ),
        )
        self.conn.commit()

    def load_paper_open(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM paper_open").fetchall()
        return [dict(r) for r in rows]

    def clear_paper_open(self, asset: str) -> None:
        self.conn.execute("DELETE FROM paper_open WHERE asset = ?", (asset,))
        self.conn.commit()

    def add_scan(self, asset: str, side: str, ask: float | None, edge: float | None) -> None:
        self.conn.execute(
            "INSERT INTO scanner (ts, asset, side, ask, edge) VALUES (?, ?, ?, ?, ?)",
            (time.time(), asset, side, ask, edge),
        )
        self.conn.commit()

    def scans(self, limit: int = 20) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM scanner ORDER BY ts DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def settings(self) -> dict:
        rows = self.conn.execute("SELECT key, value FROM settings").fetchall()
        out = {}
        for row in rows:
            out[row["key"]] = json.loads(row["value"])
        return out

    def add_param_change(
        self,
        *,
        ts: float,
        asset: str,
        strategy: str,
        param: str,
        old_value: float | None,
        new_value: float,
        pending: bool = False,
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO param_changes (ts, asset, strategy, param, old_value, new_value, pending)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (ts, asset, strategy, param, old_value, new_value, 1 if pending else 0),
        )
        self.conn.commit()

    def param_changes(self, limit: int = 40) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM param_changes ORDER BY ts DESC, id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]

    def save_setting(self, key: str, value) -> None:
        if value is None:
            self.conn.execute("DELETE FROM settings WHERE key = ?", (key,))
        else:
            self.conn.execute(
                "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (key, json.dumps(value)),
            )
        self.conn.commit()
