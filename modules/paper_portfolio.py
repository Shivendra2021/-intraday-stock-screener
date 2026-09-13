"""Paper cash account for tracking suggested picks.

This is a research-only simulation. It does not place orders.
"""

from __future__ import annotations

import datetime
import logging
import sqlite3
from typing import Any

logger = logging.getLogger(__name__)

STARTING_CASH = 50000.0


def _now() -> str:
    try:
        from modules.time_utils import now_ist

        return now_ist().isoformat(timespec="seconds")
    except Exception:
        return datetime.datetime.now().isoformat(timespec="seconds")


def _connect() -> sqlite3.Connection:
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_account() -> None:
    with _connect() as conn:
        conn.execute(
            """INSERT OR IGNORE INTO paper_account
               (id, initial_cash, cash_balance, realized_pnl, updated_at)
               VALUES (1, ?, ?, 0, ?)""",
            (STARTING_CASH, STARTING_CASH, _now()),
        )
        conn.commit()


def _account(conn: sqlite3.Connection) -> sqlite3.Row:
    row = conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()
    if row:
        return row
    conn.execute(
        """INSERT INTO paper_account
           (id, initial_cash, cash_balance, realized_pnl, updated_at)
           VALUES (1, ?, ?, 0, ?)""",
        (STARTING_CASH, STARTING_CASH, _now()),
    )
    conn.commit()
    return conn.execute("SELECT * FROM paper_account WHERE id=1").fetchone()


def allocate_for_date(date_s: str, max_picks: int = 5) -> dict[str, Any]:
    """Allocate available cash across highest-confidence picks using volatility-adjusted risk-parity sizing."""
    ensure_account()
    with _connect() as conn:
        existing = conn.execute(
            """SELECT COUNT(*)
                 FROM paper_positions pp
                 JOIN picks p ON p.id=pp.pick_id
                WHERE pp.date=?
                  AND COALESCE(p.session_type, 'morning_final')='morning_final'
                  AND COALESCE(p.is_official_morning, 1)=1""",
            (date_s,),
        ).fetchone()[0]
        if existing:
            return {"date": date_s, "allocated": 0, "reason": "already_allocated"}

        picks = conn.execute(
            """
            SELECT id, date, symbol, entry_price, sl_price, target_price, confidence, status
            FROM picks
            WHERE date=? AND entry_price > 0
              AND COALESCE(session_type, 'morning_final')='morning_final'
              AND COALESCE(is_official_morning, 1)=1
            ORDER BY confidence DESC, rank ASC, id ASC
            LIMIT ?
            """,
            (date_s, max_picks),
        ).fetchall()
        if not picks:
            return {"date": date_s, "allocated": 0, "reason": "no_picks"}

        acct = _account(conn)
        cash = float(acct["cash_balance"] or 0)
        if cash <= 0:
            return {"date": date_s, "allocated": 0, "reason": "no_cash"}

        allocated = 0.0
        allocated_count = 0
        risk_per_trade = cash * 0.02  # 2% max risk per position
        max_stock_cash = cash * 0.35  # cap individual stock allocation to 35% of total portfolio cash

        for pick in picks:
            entry = float(pick["entry_price"] or 0)
            if entry <= 0:
                continue
            remaining_cash = cash - allocated
            if remaining_cash <= 0:
                break

            sl = float(pick["sl_price"] or 0)
            risk_amount_per_share = entry - sl
            if risk_amount_per_share <= 0:
                risk_amount_per_share = entry * 0.02

            target_qty = risk_per_trade / risk_amount_per_share
            raw_allocation = min(target_qty * entry, remaining_cash, max_stock_cash)
            if raw_allocation <= 0:
                continue

            # Ensure integer share quantity
            qty = int(raw_allocation // entry)
            if qty <= 0:
                if remaining_cash >= entry and entry <= max_stock_cash:
                    qty = 1
                else:
                    continue

            actual_invested = round(qty * entry, 2)
            if actual_invested > remaining_cash:
                continue

            allocation = actual_invested
            conn.execute(
                """
                INSERT INTO paper_positions
                    (pick_id, date, symbol, entry_price, sl_price, target_price, confidence,
                     allocation, quantity, invested_amount, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'open', ?)
                """,
                (
                    pick["id"],
                    pick["date"],
                    pick["symbol"],
                    entry,
                    sl,
                    float(pick["target_price"] or 0),
                    float(pick["confidence"] or 0),
                    allocation,
                    qty,
                    allocation,
                    _now(),
                ),
            )
            allocated += allocation
            allocated_count += 1

        conn.execute(
            """
            UPDATE paper_account
            SET cash_balance=?, updated_at=?
            WHERE id=1
            """,
            (round(cash - allocated, 2), _now()),
        )
        conn.commit()
        logger.info("Paper portfolio allocated %.2f for %s across %d positions", allocated, date_s, allocated_count)
        return {"date": date_s, "allocated": round(allocated, 2), "positions": allocated_count}


def allocate_today() -> dict[str, Any]:
    try:
        from modules.time_utils import today_ist_str

        date_s = today_ist_str()
    except Exception:
        date_s = datetime.date.today().isoformat()
    return allocate_for_date(date_s)


def _exit_price(position: sqlite3.Row, pick: dict[str, Any]) -> float:
    status = str(pick.get("status") or "").lower()
    entry = float(position["entry_price"] or pick.get("entry_price") or 0)
    ret = pick.get("result_return")
    if ret is not None:
        return round(entry * (1 + float(ret) / 100), 4)
    if status == "tp_hit":
        return float(position["target_price"] or pick.get("target_price") or entry)
    if status == "sl_hit":
        return float(position["sl_price"] or pick.get("sl_price") or entry)
    return entry


def settle_closed_positions(date_s: str | None = None) -> dict[str, Any]:
    """Settle open paper positions whose matching pick has closed."""
    ensure_account()
    params: tuple[Any, ...] = ()
    date_filter = ""
    if date_s:
        date_filter = "AND pp.date=?"
        params = (date_s,)

    with _connect() as conn:
        rows = conn.execute(
            f"""
            SELECT pp.*, p.status AS pick_status, p.result_return AS pick_return,
                   p.entry_price AS pick_entry, p.sl_price AS pick_sl, p.target_price AS pick_target
            FROM paper_positions pp
            JOIN picks p ON p.id=pp.pick_id
            WHERE pp.status='open'
              AND p.status IN ('tp_hit', 'sl_hit', 'eod_closed', 'open_eod')
              {date_filter}
            ORDER BY pp.date, pp.id
            """,
            params,
        ).fetchall()

        settled = []
        for row in rows:
            pick = {
                "status": row["pick_status"],
                "result_return": row["pick_return"],
                "entry_price": row["pick_entry"],
                "sl_price": row["pick_sl"],
                "target_price": row["pick_target"],
            }
            exit_price = _exit_price(row, pick)
            qty = float(row["quantity"] or 0)
            invested = float(row["invested_amount"] or 0)
            proceeds = round(qty * exit_price, 2)
            pnl = round(proceeds - invested, 2)
            ret = round((pnl / invested) * 100, 2) if invested else 0.0
            status = str(row["pick_status"] or "eod_closed").lower()

            conn.execute(
                """
                UPDATE paper_positions
                SET status=?, exit_price=?, exit_date=?, realized_pnl=?, return_pct=?, closed_at=?
                WHERE id=?
                """,
                (status, exit_price, row["date"], pnl, ret, _now(), row["id"]),
            )
            conn.execute(
                """
                UPDATE paper_account
                SET cash_balance=cash_balance+?,
                    realized_pnl=realized_pnl+?,
                    updated_at=?
                WHERE id=1
                """,
                (proceeds, pnl, _now()),
            )
            settled.append({"symbol": row["symbol"], "status": status, "pnl": pnl, "return_pct": ret})

        conn.commit()
        if settled:
            logger.info("Paper portfolio settled %s positions", len(settled))
            try:
                from modules.auditor import audit_closed_trades
                audit_closed_trades()
            except Exception as aud_exc:
                logger.debug("Auditor trade settlement hook skipped: %s", aud_exc)
        return {"date": date_s, "settled": len(settled), "positions": settled}


def rebuild_from_picks_if_empty() -> dict[str, Any]:
    """Bootstrap paper history from existing pick rows once."""
    ensure_account()
    with _connect() as conn:
        count = conn.execute("SELECT COUNT(*) FROM paper_positions").fetchone()[0]
        dates = [
            r[0]
            for r in conn.execute(
                "SELECT DISTINCT date FROM picks WHERE COALESCE(session_type, 'morning_final')='morning_final' "
                "AND COALESCE(is_official_morning, 1)=1 ORDER BY date"
            ).fetchall()
        ]
    if count or not dates:
        return {"rebuilt": False, "reason": "already_has_positions" if count else "no_picks"}

    allocated = []
    settled = []
    for date_s in dates:
        allocated.append(allocate_for_date(date_s))
        settled.append(settle_closed_positions(date_s))
    return {"rebuilt": True, "allocated": allocated, "settled": settled}


def portfolio_summary() -> dict[str, Any]:
    rebuild_from_picks_if_empty()
    settle_closed_positions()
    with _connect() as conn:
        acct = _account(conn)
        open_rows = conn.execute(
            """
            SELECT *
            FROM paper_positions
            WHERE status='open'
            ORDER BY date DESC, confidence DESC, id DESC
            """
        ).fetchall()
        recent = conn.execute(
            """
            SELECT *
            FROM paper_positions
            ORDER BY id DESC
            LIMIT 12
            """
        ).fetchall()
        all_rows = conn.execute(
            """
            SELECT pp.*, COALESCE(su.sector, 'Unknown') AS sector
            FROM paper_positions pp
            LEFT JOIN stock_universe su ON su.symbol=pp.symbol
            ORDER BY pp.date ASC, pp.id ASC
            LIMIT 500
            """
        ).fetchall()

    open_value = sum(float(r["invested_amount"] or 0) for r in open_rows)
    cash = float(acct["cash_balance"] or 0)
    initial = float(acct["initial_cash"] or STARTING_CASH)
    realized = float(acct["realized_pnl"] or 0)
    equity = cash + open_value

    all_positions = [dict(r) for r in all_rows]
    closed_positions = [p for p in all_positions if str(p.get("status") or "").lower() != "open"]
    daily: dict[str, dict[str, Any]] = {}
    sectors: dict[str, dict[str, Any]] = {}
    curve = [{"date": "START", "equity": round(initial, 2), "pnl": 0.0, "drawdown_pct": 0.0}]
    running_equity = initial
    peak = initial

    for pos in closed_positions:
        date_s = str(pos.get("exit_date") or pos.get("date") or "")
        pnl = float(pos.get("realized_pnl") or 0.0)
        invested = float(pos.get("invested_amount") or 0.0)
        sector = str(pos.get("sector") or "Unknown")
        day = daily.setdefault(date_s, {"date": date_s, "pnl": 0.0, "trades": 0})
        day["pnl"] += pnl
        day["trades"] += 1
        sec = sectors.setdefault(sector, {"sector": sector, "invested": 0.0, "pnl": 0.0, "trades": 0})
        sec["invested"] += invested
        sec["pnl"] += pnl
        sec["trades"] += 1
        running_equity += pnl
        peak = max(peak, running_equity)
        drawdown = ((running_equity - peak) / peak * 100) if peak else 0.0
        curve.append({
            "date": date_s,
            "symbol": pos.get("symbol"),
            "equity": round(running_equity, 2),
            "pnl": round(pnl, 2),
            "drawdown_pct": round(drawdown, 2),
        })

    best = max(closed_positions, key=lambda p: float(p.get("return_pct") or -999999), default=None)
    worst = min(closed_positions, key=lambda p: float(p.get("return_pct") or 999999), default=None)
    return {
        "initial_cash": round(initial, 2),
        "cash_balance": round(cash, 2),
        "open_invested": round(open_value, 2),
        "equity": round(equity, 2),
        "realized_pnl": round(realized, 2),
        "return_pct": round((equity - initial) / initial * 100, 2) if initial else 0.0,
        "open_positions": [dict(r) for r in open_rows],
        "recent_positions": [dict(r) for r in recent],
        "positions": all_positions,
        "daily_pnl": [
            {"date": k, "pnl": round(v["pnl"], 2), "trades": v["trades"]}
            for k, v in sorted(daily.items())
        ],
        "sector_exposure": [
            {
                "sector": v["sector"],
                "invested": round(v["invested"], 2),
                "pnl": round(v["pnl"], 2),
                "trades": v["trades"],
            }
            for v in sorted(sectors.values(), key=lambda x: abs(x["pnl"]), reverse=True)
        ],
        "equity_curve": curve,
        "best_pick": dict(best) if best else None,
        "worst_pick": dict(worst) if worst else None,
        "updated_at": acct["updated_at"],
    }


if __name__ == "__main__":
    print(portfolio_summary())
