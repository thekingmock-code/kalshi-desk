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
            """
        )
        self.conn.commit()

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
        self.conn.execute("DELETE FROM journal")
        self.conn.execute("DELETE FROM scanner")
        self.conn.execute("DELETE FROM paper_buys")
        self.conn.execute("DELETE FROM paper_orders")
        self.conn.execute("DELETE FROM paper_open")
        self.conn.execute("DELETE FROM shadow_paper")
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

    def save_setting(self, key: str, value) -> None:
        self.conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, json.dumps(value)),
        )
        self.conn.commit()
