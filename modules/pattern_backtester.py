"""Pattern backtest table and proven-edge gate."""

from __future__ import annotations

import datetime
import logging
import sqlite3

logger = logging.getLogger(__name__)


def _upsert_backtest(conn: sqlite3.Connection, key: str, wins: int, losses: int, returns: list[float], source: str) -> None:
    from config import PATTERN_MIN_AVG_RETURN, PATTERN_MIN_BACKTEST_TRADES, PATTERN_MIN_HIT_RATE

    total = wins + losses
    hit_rate = wins / total if total else 0.0
    avg_return = sum(returns) / len(returns) if returns else (hit_rate - 0.5) * 4
    max_loss = min(returns) if returns else 0.0
    proven = (
        total >= PATTERN_MIN_BACKTEST_TRADES
        and hit_rate >= PATTERN_MIN_HIT_RATE
        and avg_return >= PATTERN_MIN_AVG_RETURN
    )
    today = datetime.date.today().isoformat()
    conn.execute(
        """INSERT INTO pattern_backtests
           (pattern_key, total_trades, wins, losses, hit_rate, avg_return,
            max_loss, proven_edge, source, last_backtest)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(pattern_key) DO UPDATE SET
             total_trades=excluded.total_trades,
             wins=excluded.wins,
             losses=excluded.losses,
             hit_rate=excluded.hit_rate,
             avg_return=excluded.avg_return,
             max_loss=excluded.max_loss,
             proven_edge=excluded.proven_edge,
             source=excluded.source,
             last_backtest=excluded.last_backtest""",
        (
            key,
            total,
            wins,
            losses,
            round(hit_rate, 4),
            round(avg_return, 4),
            round(max_loss, 4),
            1 if proven else 0,
            source,
            today,
        ),
    )


def refresh_pattern_backtests(pattern_keys: list[str] | None = None) -> dict:
    from config import DB_PATH, PATTERN_MIN_AVG_RETURN, PATTERN_MIN_BACKTEST_TRADES, PATTERN_MIN_HIT_RATE
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    today = datetime.date.today().isoformat()
    updated = 0

    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        if pattern_keys is None:
            rows = conn.execute(
                """SELECT DISTINCT pattern_key FROM (
                   SELECT pattern_key FROM patterns
                   UNION SELECT pattern_key FROM market_winners
                   UNION SELECT pattern_key FROM market_losers
                   UNION SELECT pattern_key FROM pattern_outcomes
                ) WHERE pattern_key IS NOT NULL AND pattern_key != ''"""
            ).fetchall()
            keys = [r[0] for r in rows]
        else:
            keys = sorted({k for k in pattern_keys if k})

        for key in keys:
            outcome_rows = conn.execute(
                "SELECT outcome, result_return FROM pattern_outcomes WHERE pattern_key=?",
                (key,),
            ).fetchall()
            wins = sum(1 for r in outcome_rows if r["outcome"] == "target_hit")
            losses = sum(1 for r in outcome_rows if r["outcome"] == "stopped_out")
            returns = [r["result_return"] for r in outcome_rows if r["result_return"] is not None]

            market_wins = conn.execute(
                "SELECT COUNT(*) FROM market_winners WHERE pattern_key=?", (key,)
            ).fetchone()[0]
            market_losses = conn.execute(
                "SELECT COUNT(*) FROM market_losers WHERE pattern_key=?", (key,)
            ).fetchone()[0]

            wins += market_wins
            losses += market_losses
            total = wins + losses
            if total == 0:
                existing = conn.execute(
                    "SELECT source FROM pattern_backtests WHERE pattern_key=?", (key,)
                ).fetchone()
                if existing:
                    continue
            _upsert_backtest(conn, key, wins, losses, returns, "pattern_outcomes+market_winners_losers")
            updated += 1
        conn.commit()

    logger.info("Pattern backtests refreshed: %s", updated)
    return {"patterns_updated": updated}


def bootstrap_historical_backtests(candidates: list[dict]) -> dict:
    """
    Build real OHLCV backtests for candidate pattern keys when there is no
    existing evidence. Uses previous-day indicator pattern, then checks next
    day high/low/close against the configured SL/target assumptions.
    """
    from config import DB_PATH, MAX_SL_PCT, MIN_TARGET_MOVE_PCT
    from modules.analyzer import _build_pattern_key, _calculate_indicators
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    try:
        import yfinance as yf
    except Exception as exc:
        logger.warning("Historical backtest skipped, yfinance unavailable: %s", exc)
        return {"patterns_updated": 0}

    wanted = sorted({c.get("pattern_key") for c in candidates if c.get("pattern_key")})
    if not wanted:
        return {"patterns_updated": 0}

    aggregates = {key: {"wins": 0, "losses": 0, "returns": []} for key in wanted}

    for candidate in candidates:
        symbol = candidate.get("symbol")
        wanted_key = candidate.get("pattern_key")
        if not symbol or not wanted_key:
            continue
        try:
            df = yf.download(f"{symbol}.NS", period="1y", interval="1d", auto_adjust=True, progress=False)
            if df is None or df.empty or len(df) < 80:
                continue
            df.columns = [c[0].lower() if isinstance(c, tuple) else str(c).lower() for c in df.columns]

            for i in range(60, len(df) - 1):
                hist = df.iloc[:i]
                ind = _calculate_indicators(hist)
                if not ind or _build_pattern_key(ind) != wanted_key:
                    continue

                next_day = df.iloc[i]
                entry = float(next_day["open"])
                high = float(next_day["high"])
                low = float(next_day["low"])
                close = float(next_day["close"])
                if entry <= 0:
                    continue

                target = entry * (1 + MIN_TARGET_MOVE_PCT / 100)
                stop = entry * (1 - MAX_SL_PCT / 100)
                hit_target = high >= target
                hit_stop = low <= stop

                if hit_target and not hit_stop:
                    ret = (target - entry) / entry * 100
                    aggregates[wanted_key]["wins"] += 1
                elif hit_stop:
                    ret = (stop - entry) / entry * 100
                    aggregates[wanted_key]["losses"] += 1
                else:
                    ret = (close - entry) / entry * 100
                    if ret > 0:
                        aggregates[wanted_key]["wins"] += 1
                    else:
                        aggregates[wanted_key]["losses"] += 1
                aggregates[wanted_key]["returns"].append(ret)
        except Exception as exc:
            logger.debug("Historical backtest failed for %s: %s", symbol, exc)

    updated = 0
    with sqlite3.connect(DB_PATH) as conn:
        for key, data in aggregates.items():
            if data["wins"] + data["losses"] == 0:
                continue
            _upsert_backtest(
                conn,
                key,
                data["wins"],
                data["losses"],
                data["returns"],
                "historical_ohlcv_candidate_bootstrap",
            )
            updated += 1
        conn.commit()

    logger.info("Historical candidate backtests updated: %s", updated)
    return {"patterns_updated": updated}


def get_pattern_edge(pattern_key: str) -> dict:
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT * FROM pattern_backtests WHERE pattern_key=?", (pattern_key,)
        ).fetchone()
    if not row:
        return {"pattern_key": pattern_key, "proven_edge": False, "reason": "no backtest rows"}
    data = dict(row)
    data["proven_edge"] = bool(data.get("proven_edge"))
    if not data["proven_edge"]:
        data["reason"] = (
            f"trades={data.get('total_trades', 0)}, "
            f"hit_rate={data.get('hit_rate', 0):.2f}, "
            f"avg_return={data.get('avg_return', 0):.2f}"
        )
    return data


def filter_candidates_by_edge(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    accepted = []
    rejected = []
    pattern_keys = [c.get("pattern_key") for c in candidates if c.get("pattern_key")]
    refresh_pattern_backtests(pattern_keys)
    bootstrap_historical_backtests(candidates)

    for candidate in candidates:
        key = candidate.get("pattern_key", "")
        edge = get_pattern_edge(key)
        enriched = {**candidate, "edge": edge}
        if edge.get("proven_edge"):
            enriched["edge_status"] = "proven"
            accepted.append(enriched)
        else:
            enriched["edge_status"] = "rejected"
            enriched["edge_reject_reason"] = edge.get("reason", "unproven")
            rejected.append(enriched)

    return accepted, rejected
