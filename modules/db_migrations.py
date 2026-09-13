"""Small SQLite migrations for research-quality gates."""

from __future__ import annotations

import sqlite3


def _columns(conn: sqlite3.Connection, table: str) -> set[str]:
    return {row[1] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}


def _add_column(conn: sqlite3.Connection, table: str, name: str, ddl: str) -> None:
    if name not in _columns(conn, table):
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {ddl}")


def ensure_research_tables() -> None:
    from config import DB_PATH

    conn = sqlite3.connect(DB_PATH)
    try:
        # ── Performance PRAGMAs: WAL mode for concurrent agent access ──────────
        conn.execute("PRAGMA journal_mode = WAL;")
        conn.execute("PRAGMA synchronous = NORMAL;")
        conn.execute("PRAGMA busy_timeout = 5000;")

        # Core tables used by dashboard and bot startup. Keep schemas permissive so
        # older installs can start and then evolve through additive migrations.
        conn.execute(
            """CREATE TABLE IF NOT EXISTS stock_universe (
               symbol TEXT PRIMARY KEY,
               exchange TEXT,
               sector TEXT,
               is_active INTEGER DEFAULT 1,
               last_verified TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS picks (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT,
               rank INTEGER,
               symbol TEXT,
               entry_price REAL,
               sl_price REAL,
               target_price REAL,
               confidence REAL,
               signal_reasons TEXT,
               status TEXT DEFAULT 'open',
               result_return REAL,
               created_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS daily_accuracy (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT UNIQUE,
               tp_count INTEGER DEFAULT 0,
               sl_count INTEGER DEFAULT 0,
               total INTEGER DEFAULT 0,
               accuracy REAL DEFAULT 0,
               avg_return REAL DEFAULT 0
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS patterns (
               pattern_key TEXT PRIMARY KEY,
               success_rate REAL DEFAULT 0,
               sample_count INTEGER DEFAULT 0,
               source TEXT,
               proven_level TEXT,
               is_anti_pattern INTEGER DEFAULT 0,
               last_market_update TEXT
            )"""
        )

        conn.execute(
            """CREATE TABLE IF NOT EXISTS price_validations (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT,
               symbol TEXT,
               yahoo_price REAL,
               nse_price REAL,
               broker_price REAL,
               consensus_price REAL,
               spread_pct REAL,
               sources_ok INTEGER,
               status TEXT,
               details TEXT,
               created_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS pattern_backtests (
               pattern_key TEXT PRIMARY KEY,
               total_trades INTEGER,
               wins INTEGER,
               losses INTEGER,
               hit_rate REAL,
               avg_return REAL,
               max_loss REAL,
               proven_edge INTEGER DEFAULT 0,
               source TEXT,
               last_backtest TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS pattern_outcomes (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT,
               symbol TEXT,
               pattern_key TEXT,
               entry_price REAL,
               sl_price REAL,
               target_price REAL,
               intraday_high REAL,
               intraday_low REAL,
               close_price REAL,
               outcome TEXT,
               result_return REAL,
               score REAL,
               created_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS grok_evidence_reviews (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT,
               event_type TEXT,
               candidate_count INTEGER,
               verdict TEXT,
               risk_level TEXT,
               brief_review TEXT,
               next_action TEXT,
               created_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS candidate_audit (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT,
               stage TEXT,
               symbol TEXT,
               accepted INTEGER DEFAULT 0,
               score REAL,
               adjusted_score REAL,
               confidence_delta REAL DEFAULT 0,
               data_quality_score REAL,
               reliability_score REAL,
               similarity_score REAL,
               agreement_score REAL,
               reasons_json TEXT,
               snapshot_json TEXT,
               created_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS data_quality_snapshots (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT,
               stage TEXT,
               universe_count INTEGER,
               active_symbols INTEGER,
               price_validation_score REAL,
               provider_reliability_score REAL,
               terminal_freshness_score REAL,
               overall_score REAL,
               status TEXT,
               details_json TEXT,
               created_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS provider_reliability (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT,
               provider TEXT,
               ok_count INTEGER DEFAULT 0,
               fail_count INTEGER DEFAULT 0,
               score REAL DEFAULT 0,
               last_error TEXT,
               updated_at TEXT,
               UNIQUE(date, provider)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS grok_dashboard_snapshots (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT,
               market_status TEXT,
               payload_json TEXT,
               ai_model TEXT,
               ai_status TEXT,
               created_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS ollama_intraday_candidates (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT NOT NULL,
               scan_time TEXT,
               symbol TEXT NOT NULL,
               return_pct REAL,
               open_to_high_pct REAL,
               open_to_close_pct REAL,
               gap_pct REAL,
               first_15m_return_pct REAL,
               first_15m_volume_ratio REAL,
               volume_ratio REAL,
               prev_day_change_pct REAL,
               weekly_change_pct REAL,
               sector TEXT,
               score REAL,
               features_json TEXT,
               created_at TEXT DEFAULT CURRENT_TIMESTAMP,
               UNIQUE(date, scan_time, symbol)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS ollama_winner_studies (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT NOT NULL,
               scan_time TEXT,
               model TEXT,
               symbols_json TEXT,
               patterns_json TEXT,
               summary TEXT,
               prompt_hash TEXT,
               created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )"""
        )

        conn.execute(
            """CREATE TABLE IF NOT EXISTS after_market_winner_features (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT NOT NULL,
               symbol TEXT NOT NULL,
               return_pct REAL,
               open_to_high_pct REAL,
               open_to_close_pct REAL,
               volume_ratio REAL,
               gap_pct REAL,
               rsi REAL,
               adx REAL,
               ema_alignment TEXT,
               sector TEXT,
               pattern_key TEXT,
               features_json TEXT,
               created_at TEXT DEFAULT CURRENT_TIMESTAMP,
               UNIQUE(date, symbol)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS after_market_learned_patterns (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               date TEXT NOT NULL,
               pattern_key TEXT NOT NULL,
               confidence REAL,
               support_count INTEGER,
               avg_return_pct REAL,
               rules_json TEXT,
               created_at TEXT DEFAULT CURRENT_TIMESTAMP,
               UNIQUE(date, pattern_key)
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS paper_account (
               id INTEGER PRIMARY KEY CHECK (id=1),
               initial_cash REAL DEFAULT 50000,
               cash_balance REAL DEFAULT 50000,
               realized_pnl REAL DEFAULT 0,
               updated_at TEXT
            )"""
        )
        conn.execute(
            """CREATE TABLE IF NOT EXISTS paper_positions (
               id INTEGER PRIMARY KEY AUTOINCREMENT,
               pick_id INTEGER UNIQUE,
               date TEXT,
               symbol TEXT,
               entry_price REAL,
               sl_price REAL,
               target_price REAL,
               confidence REAL,
               allocation REAL,
               quantity REAL,
               invested_amount REAL,
               status TEXT DEFAULT 'open',
               exit_price REAL,
               exit_date TEXT,
               realized_pnl REAL DEFAULT 0,
               return_pct REAL DEFAULT 0,
               created_at TEXT,
               closed_at TEXT
            )"""
        )
        conn.execute(
            """INSERT OR IGNORE INTO paper_account
               (id, initial_cash, cash_balance, realized_pnl, updated_at)
               VALUES (1, 50000, 50000, 0, CURRENT_TIMESTAMP)"""
        )

        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if "picks" in tables:
            _add_column(conn, "picks", "pattern_key", "TEXT")
            _add_column(conn, "picks", "validated_price", "REAL")
            _add_column(conn, "picks", "price_validation_status", "TEXT")
            _add_column(conn, "picks", "edge_status", "TEXT")
            _add_column(conn, "picks", "grok_review", "TEXT")
            _add_column(conn, "picks", "session_type", "TEXT DEFAULT 'morning_final'")
            _add_column(conn, "picks", "is_official_morning", "INTEGER DEFAULT 1")
            _add_column(conn, "picks", "source_label", "TEXT")
            _add_column(conn, "picks", "data_quality_score", "REAL")
            _add_column(conn, "picks", "provider_reliability_score", "REAL")
            _add_column(conn, "picks", "similarity_score", "REAL")
            _add_column(conn, "picks", "agreement_score", "REAL")
            _add_column(conn, "picks", "confidence_delta", "REAL DEFAULT 0")
            _add_column(conn, "picks", "quality_reasons", "TEXT")

        if "paper_positions" in tables:
            _add_column(conn, "paper_positions", "quantity", "REAL")
            _add_column(conn, "paper_positions", "invested_amount", "REAL")

        conn.commit()
    finally:
        conn.close()
