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
