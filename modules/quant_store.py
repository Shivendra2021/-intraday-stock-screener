"""Durable, separate quant research store. Never rewrites legacy history.

Times are epoch seconds (UTC); session dates are Asia/Kolkata. Candle timestamps
denote bar OPEN. Signals and observation features are immutable after insertion.
"""
from __future__ import annotations

import contextlib
import json
import os
import sqlite3
import time


def dumps(value):
    return json.dumps(value, allow_nan=False, default=str, separators=(",", ":"))


class Store:
    def __init__(self, path=None):
        if path is None:
            from config import QUANT_DB_PATH
            path = QUANT_DB_PATH
        self.path = str(path)
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        with self.connect() as c:
            c.executescript("""
                CREATE TABLE IF NOT EXISTS bars (
                    symbol TEXT NOT NULL, interval TEXT NOT NULL, ts INTEGER NOT NULL,
                    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL,
                    close REAL NOT NULL, volume REAL NOT NULL, source TEXT NOT NULL,
                    PRIMARY KEY(symbol, interval, ts));
                CREATE TABLE IF NOT EXISTS state (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS observations (
                    id TEXT PRIMARY KEY, date TEXT NOT NULL, symbol TEXT NOT NULL,
                    ts INTEGER NOT NULL, features TEXT NOT NULL, setup TEXT NOT NULL,
                    reason TEXT NOT NULL, provenance TEXT NOT NULL);
                CREATE INDEX IF NOT EXISTS obs_date ON observations(date);
                CREATE TABLE IF NOT EXISTS outcomes (
                    observation_id TEXT PRIMARY KEY REFERENCES observations(id),
                    value TEXT NOT NULL, resolved INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS signals (
                    id TEXT PRIMARY KEY REFERENCES observations(id), date TEXT NOT NULL,
                    symbol TEXT NOT NULL, value TEXT NOT NULL, pick_id INTEGER,
                    notified INTEGER NOT NULL DEFAULT 0, closed_notified INTEGER NOT NULL DEFAULT 0,
                    UNIQUE(date,symbol));
                CREATE TABLE IF NOT EXISTS models (
                    id TEXT PRIMARY KEY, created_at INTEGER NOT NULL, value TEXT NOT NULL,
                    promoted INTEGER NOT NULL DEFAULT 0);
                CREATE TABLE IF NOT EXISTS review_ledger (
                    observation_id TEXT PRIMARY KEY REFERENCES observations(id), date TEXT NOT NULL,
                    symbol TEXT NOT NULL, decision TEXT NOT NULL, payload TEXT NOT NULL,
                    created_at INTEGER NOT NULL);
                CREATE INDEX IF NOT EXISTS review_date ON review_ledger(date, decision);
                CREATE TABLE IF NOT EXISTS leases (name TEXT PRIMARY KEY, expires REAL NOT NULL);
            """)

    @contextlib.contextmanager
    def connect(self):
        c = sqlite3.connect(self.path, timeout=15)
        c.row_factory = sqlite3.Row
        c.execute("PRAGMA busy_timeout=15000")
        c.execute("PRAGMA journal_mode=WAL")
        c.execute("PRAGMA foreign_keys=ON")
        try:
            yield c
            c.commit()
        except BaseException:
            c.rollback()
            raise
        finally:
            c.close()

    def get(self, key, default=None):
        with self.connect() as c:
            r = c.execute("SELECT value FROM state WHERE key=?", (key,)).fetchone()
        return json.loads(r[0]) if r else default

    def put(self, key, value):
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO state VALUES (?,?)", (key, dumps(value)))

    @contextlib.contextmanager
    def lease(self, name, seconds=900):
        now = time.time()
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            c.execute("DELETE FROM leases WHERE name=? AND expires<?", (name, now))
            changed = c.execute("INSERT OR IGNORE INTO leases VALUES (?,?)", (name, now + seconds)).rowcount
        try:
            yield bool(changed)
        finally:
            if changed:
                with self.connect() as c:
                    c.execute("DELETE FROM leases WHERE name=? AND expires=?", (name, now + seconds))

    def save_bars(self, symbol, interval, frame, source):
        rows = []
        for r in frame.itertuples():
            rows.append((symbol, interval, int(r.Index.timestamp()), float(r.open),
                         float(r.high), float(r.low), float(r.close), float(r.volume), source))
        with self.connect() as c:
            c.executemany("INSERT OR REPLACE INTO bars VALUES (?,?,?,?,?,?,?,?,?)", rows)

    def bars(self, symbol, interval, before=None):
        import pandas as pd
        sql = "SELECT ts,open,high,low,close,volume FROM bars WHERE symbol=? AND interval=?"
        args = [symbol, interval]
        if before is not None:
            sql += " AND ts<?"
            args.append(int(before))
        with self.connect() as c:
            rows = c.execute(sql + " ORDER BY ts", args).fetchall()
        df = pd.DataFrame([tuple(r) for r in rows], columns=["ts", "open", "high", "low", "close", "volume"])
        df.index = pd.to_datetime(df.pop("ts"), unit="s", utc=True).dt.tz_convert("Asia/Kolkata")
        return df

    def observe(self, row, reason, provenance="live"):
        # Same timestamp/feature version cannot be silently rewritten by a later scan.
        ident = f"v3:{row['symbol']}:{int(row['ts'])}"
        with self.connect() as c:
            c.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?,?)", (
                ident, row["date"], row["symbol"], int(row["ts"]), dumps(row),
                row.get("setup", "none"), reason, provenance))
        return ident

    def outcome(self, ident, value):
        with self.connect() as c:
            c.execute("INSERT INTO outcomes VALUES (?,?,?) ON CONFLICT(observation_id) DO UPDATE SET "
                      "value=excluded.value,resolved=excluded.resolved WHERE outcomes.resolved=0",
                      (ident, dumps(value), int(value.get("resolved", False))))

    def save_replay(self, records):
        """One transaction per session, rather than two disk commits per candle."""
        with self.connect() as c:
            for row, reason, outcome in records:
                ident = f"v3:{row['symbol']}:{int(row['ts'])}"
                c.execute("INSERT OR IGNORE INTO observations VALUES (?,?,?,?,?,?,?,?)", (
                    ident, row["date"], row["symbol"], int(row["ts"]), dumps(row),
                    row.get("setup", "none"), reason, "historical_current_universe"))
                # A historical replay must never settle a live signal using
                # research entry assumptions instead of its recorded quote.
                existing = c.execute("SELECT provenance FROM observations WHERE id=?", (ident,)).fetchone()
                if existing[0] != "live" and not c.execute("SELECT 1 FROM signals WHERE id=?", (ident,)).fetchone():
                    c.execute("INSERT INTO outcomes VALUES (?,?,?) ON CONFLICT(observation_id) DO UPDATE SET "
                              "value=excluded.value,resolved=excluded.resolved WHERE outcomes.resolved=0",
                              (ident, dumps(outcome), int(outcome.get("resolved", False))))

    def signals(self, date=None):
        with self.connect() as c:
            rows = c.execute("SELECT * FROM signals" + (" WHERE date=?" if date else "") + " ORDER BY rowid",
                             (date,) if date else ()).fetchall()
        return [{**dict(r), "value": json.loads(r["value"])} for r in rows]

    def add_signal(self, ident, row):
        from config import QUANT_MAX_PICKS
        with self.connect() as c:
            c.execute("BEGIN IMMEDIATE")
            count = c.execute("SELECT COUNT(*) FROM signals WHERE date=?", (row["date"],)).fetchone()[0]
            if count >= QUANT_MAX_PICKS:
                return False
            return bool(c.execute("INSERT OR IGNORE INTO signals(id,date,symbol,value) VALUES (?,?,?,?)",
                                  (ident, row["date"], row["symbol"], dumps(row))).rowcount)

    def record_review(self, ident, row, decision, review):
        """Persist the deterministic decision trace for a point-in-time observation."""
        with self.connect() as c:
            c.execute("INSERT OR REPLACE INTO review_ledger VALUES (?,?,?,?,?,?)", (
                ident, row["date"], row["symbol"], decision, dumps(review), int(time.time())))

    def reviews(self, date=None):
        with self.connect() as c:
            rows = c.execute("SELECT * FROM review_ledger" + (" WHERE date=?" if date else "") +
                             " ORDER BY created_at, symbol", (date,) if date else ()).fetchall()
        return [{**dict(row), "payload": json.loads(row["payload"])} for row in rows]
