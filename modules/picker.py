# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
picker.py — Convert analyzer output to final top-5 picks with entry/SL/target.
"""

import sqlite3
import logging
import datetime
import json

from modules.time_utils import now_ist, today_ist_str

logger = logging.getLogger(__name__)


def _calculate_levels(stock: dict) -> dict | None:
    """
    Calculate entry, SL, target, and risk-reward for one stock.
    Returns None if risk-reward < MIN_RISK_REWARD.
    Dynamically targets 5.0% - 8.0% return based on the stock's prime intraday period.
    """
    from config import (SL_ATR_MULTIPLIER, MAX_SL_PCT, MIN_RISK_REWARD,
                        MIN_TARGET_MOVE_PCT, MAX_TARGET_MOVE_PCT)
    from modules.grok_brain import evaluate_stock_intraday_period

    price = stock["price"]
    atr   = stock["atr"]

    # Evaluate intraday timing and high-return target
    timing = evaluate_stock_intraday_period(stock)
    move_pct = timing.get("target_return_pct") or ((MIN_TARGET_MOVE_PCT + MAX_TARGET_MOVE_PCT) / 2)

    # Dynamic AI Structural Stop Loss (0.5% - 3.0%)
    ai_sl = timing.get("ai_sl_pct")
    if ai_sl is not None and ai_sl > 0:
        sl_pct_val = min(float(MAX_SL_PCT), max(0.5, float(ai_sl)))
        sl_price = price * (1 - sl_pct_val / 100)
    else:
        # Fallback to ATR-based dynamic stop bounded by [0.5, MAX_SL_PCT]
        sl_atr  = price - (atr * SL_ATR_MULTIPLIER)
        sl_pct  = price * (1 - MAX_SL_PCT / 100)
        sl_price = max(sl_atr, sl_pct)
        sl_pct_val = ((price - sl_price) / price * 100) if price > 0 else 1.5

    from config import RUNNER_TP1_PCT, RUNNER_TP2_PCT
    ai_tp1_pct = float(timing.get("tp1_pct") or RUNNER_TP1_PCT)
    ai_tp2_pct = float(timing.get("tp2_pct") or RUNNER_TP2_PCT)
    tp1_price = price * (1 + ai_tp1_pct / 100)
    tp2_price = price * (1 + ai_tp2_pct / 100)
    target_price = tp2_price

    risk   = price - sl_price
    reward = target_price - price

    if risk <= 0:
        return None

    rr = reward / risk
    if rr < MIN_RISK_REWARD:
        return None

    upside_pct = ((target_price - price) / price * 100) if price and price > 0 else 0.0

    return {
        **stock,
        "entry_price":       round(price, 2),
        "sl_price":          round(sl_price, 2),
        "sl_pct":            round(sl_pct_val, 2),
        "sl_type":           "ai_dynamic_structural",
        "target_price":      round(target_price, 2),
        "tp1_price":         round(tp1_price, 2),
        "tp2_price":         round(tp2_price, 2),
        "tp1_pct":           round(ai_tp1_pct, 2),
        "tp2_pct":           round(ai_tp2_pct, 2),
        "upside_pct":        round(upside_pct, 2),
        "risk_reward":       round(rr, 2),
        "prime_window":      timing.get("prime_window"),
        "period_code":       timing.get("period_code"),
        "target_return_pct": timing.get("target_return_pct"),
        "timing_strategy":   timing.get("strategy"),
        "time_cutoff":       timing.get("time_cutoff"),
        "edge_rationale":    timing.get("edge_rationale"),
    }


def _write_picks_to_db(
    picks: list,
    session_type: str = "morning_final",
    is_official_morning: bool = True,
    source_label: str = "official_morning_pipeline",
):
    """Insert picks into the picks table."""
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    today = today_ist_str()
    now   = now_ist().isoformat()

    with sqlite3.connect(DB_PATH) as conn:
        # Clear today's pending picks first (avoid duplicates on re-run)
        conn.execute(
            "DELETE FROM picks WHERE date=? AND status='pending' AND COALESCE(session_type, 'morning_final')=?",
            (today, session_type),
        )
        for i, p in enumerate(picks, start=1):
            conn.execute(
                """INSERT INTO picks
                   (date, rank, symbol, entry_price, sl_price, target_price,
                    confidence, signal_reasons, status, created_at, pattern_key,
                    validated_price, price_validation_status, edge_status, grok_review,
                    session_type, is_official_morning, source_label, data_quality_score,
                    provider_reliability_score, similarity_score, agreement_score,
                    confidence_delta, quality_reasons)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (today, i, p["symbol"], p["entry_price"], p["sl_price"],
                 p["target_price"], p["score"], p.get("signal_reasons", ""), now,
                 p.get("pattern_key", ""), p.get("validated_price"),
                 p.get("price_validation_status", ""), p.get("edge_status", ""),
                 p.get("grok_review", ""), session_type, 1 if is_official_morning else 0,
                 source_label, p.get("data_quality_score"), p.get("provider_reliability_score"),
                 p.get("similarity_score"), p.get("agreement_score"), p.get("confidence_delta", 0),
                 p.get("quality_reasons", ""))
            )
        conn.commit()
    logger.info("Wrote %s picks to DB for %s session=%s official=%s", len(picks), today, session_type, is_official_morning)

    try:
        save_picks_to_history_json(picks)
    except Exception as exc:
        logger.error("Could not write daily picks to JSON history: %s", exc)

    try:
        from modules.auditor import record_alert_snapshot
        for p in picks:
            record_alert_snapshot(p["symbol"], p)
    except Exception as exc:
        logger.debug("Could not record auditor alert snapshot: %s", exc)


def get_system_accuracy_stats() -> dict:
    """Calculate overall system accuracy from the picks database."""
    from config import DB_PATH
    try:
        with sqlite3.connect(DB_PATH) as conn:
            from config import QUANT_ENABLED
            scope = "source_label LIKE 'quant_v3:%'" if QUANT_ENABLED else "COALESCE(is_official_morning,1)=1"
            tp, sl, closed, wins = conn.execute(f"SELECT SUM(status='tp_hit'),SUM(status='sl_hit'),COUNT(*),SUM(result_return>0) FROM picks WHERE {scope} AND result_return IS NOT NULL AND status NOT IN ('pending','unfilled','unresolved')").fetchone()
            tp, sl, wins = int(tp or 0), int(sl or 0), int(wins or 0)
            win_rate = (wins / closed * 100) if closed > 0 else 0.0
            avg_row = conn.execute(f"SELECT AVG(result_return) FROM picks WHERE {scope} AND result_return IS NOT NULL AND status NOT IN ('pending','unfilled','unresolved')").fetchone()
            avg_ret = avg_row[0] if (avg_row and avg_row[0] is not None) else 0.0
            label = f"{round(win_rate, 1)}% Net-positive paper fills" if closed > 0 else "0 Closed Paper Fills"
            sublabel = f"{wins} positive / {closed} closed" if closed > 0 else "Collecting evidence"
            return {
                "win_rate": round(win_rate, 1),
                "tp_count": tp,
                "sl_count": sl,
                "total_closed": closed,
                "avg_return": round(float(avg_ret), 2),
                "label": label,
                "sublabel": sublabel,
            }
    except Exception as exc:
        logger.debug("Could not compute system accuracy: %s", exc)
        return {
            "win_rate": 0.0,
            "tp_count": 0,
            "sl_count": 0,
            "total_closed": 0,
            "avg_return": 0.0,
            "label": "0 Closed Trades",
            "sublabel": "Awaiting Market Execution",
        }


get_historical_accuracy = get_system_accuracy_stats


def save_picks_to_history_json(picks: list, date_str: str | None = None, timestamp_str: str | None = None) -> None:
    """Save daily picks in JSON format to DAILY_PICKS_JSON_PATH (guaranteed Top 3)."""
    from config import DAILY_PICKS_JSON_PATH
    import os

    if not picks:
        return

    # Strictly Top 3 picks
    picks = picks[:3]

    today = date_str or today_ist_str()
    iso_now = timestamp_str or now_ist().isoformat()
    try:
        display_time = now_ist().strftime("%I:%M %p")
    except Exception:
        display_time = "09:00 AM"

    formatted_picks = []
    for i, p in enumerate(picks, start=1):
        formatted_picks.append({
            "rank": p.get("rank", i),
            "symbol": p.get("symbol"),
            "entry_price": round(float(p.get("entry_price") or p.get("price", 0)), 2),
            "sl_price": round(float(p.get("sl_price", 0)), 2),
            "target_price": round(float(p.get("target_price", 0)), 2),
            "upside_pct": round(float(p.get("upside_pct", 0)), 2),
            "risk_reward": round(float(p.get("risk_reward", 0)), 2),
            "confidence": round(float(p.get("score") or p.get("confidence", 0)), 1),
            "status": p.get("status", "pending"),
            "sector": p.get("sector", "Equities"),
            "signal_reasons": p.get("signal_reasons", ""),
            "prime_window": p.get("prime_window", "09:15 - 10:15 AM (Morning Momentum)"),
            "timing_strategy": p.get("timing_strategy", "Opening Range Breakout (ORB) on 2x+ Vol Surge"),
            "target_return_pct": p.get("target_return_pct", round(float(p.get("upside_pct", 6.0)), 2)),
            "created_at": iso_now,
        })

    record = {
        "date": today,
        "timestamp": iso_now,
        "display_time": display_time,
        "picks_count": len(formatted_picks),
        "picks": formatted_picks,
    }

    history = []
    if os.path.exists(DAILY_PICKS_JSON_PATH):
        try:
            with open(DAILY_PICKS_JSON_PATH, "r", encoding="utf-8") as f:
                raw_history = json.load(f)
                if isinstance(raw_history, list):
                    # Enforce Top 3 on all historical items as well
                    for h in raw_history:
                        h["picks"] = h.get("picks", [])[:3]
                        h["picks_count"] = len(h["picks"])
                    history = raw_history
        except Exception as err:
            logger.warning("Could not read existing daily picks JSON history: %s", err)
            history = []

    # Replace or prepend today's entry
    history = [h for h in history if h.get("date") != today]
    history.insert(0, record)

    os.makedirs(os.path.dirname(DAILY_PICKS_JSON_PATH) or ".", exist_ok=True)
    temp_path = f"{DAILY_PICKS_JSON_PATH}.tmp"
    try:
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(history, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, DAILY_PICKS_JSON_PATH)
        logger.info("Saved %s picks to daily JSON history file: %s", len(formatted_picks), DAILY_PICKS_JSON_PATH)
    except Exception as exc:
        logger.error("Failed to save daily picks JSON history: %s", exc)
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def load_picks_history_json() -> list[dict]:
    """Load daily picks history from JSON file (guaranteed Top 3 picks per session)."""
    from config import DAILY_PICKS_JSON_PATH, DB_PATH
    import os

    if os.path.exists(DAILY_PICKS_JSON_PATH):
        try:
            with open(DAILY_PICKS_JSON_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list) and data:
                    # Enforce top 3 picks across all records
                    needs_resave = False
                    for rec in data:
                        if len(rec.get("picks", [])) > 3:
                            rec["picks"] = rec["picks"][:3]
                            rec["picks_count"] = 3
                            needs_resave = True
                    if needs_resave:
                        with open(DAILY_PICKS_JSON_PATH, "w", encoding="utf-8") as fw:
                            json.dump(data, fw, indent=2)
                    return data
        except Exception as e:
            logger.warning("Failed loading picks history json: %s", e)

    # Bootstrap from database if JSON file is absent or empty
    records = []
    try:
        with sqlite3.connect(DB_PATH) as conn:
            conn.row_factory = sqlite3.Row
            dates = [r[0] for r in conn.execute("SELECT DISTINCT date FROM picks ORDER BY date DESC").fetchall()]
            for d in dates:
                rows = [dict(r) for r in conn.execute("SELECT * FROM picks WHERE date=? ORDER BY rank ASC LIMIT 3", (d,)).fetchall()]
                if not rows:
                    continue
                ts = rows[0].get("created_at") or f"{d}T09:00:00"
                formatted = []
                for r in rows:
                    formatted.append({
                        "rank": r.get("rank"),
                        "symbol": r.get("symbol"),
                        "entry_price": r.get("entry_price"),
                        "sl_price": r.get("sl_price"),
                        "target_price": r.get("target_price"),
                        "confidence": r.get("confidence"),
                        "status": r.get("status", "pending"),
                        "result_return": r.get("result_return"),
                        "signal_reasons": r.get("signal_reasons", ""),
                        "sector": r.get("sector", "Equities"),
                    })
                records.append({
                    "date": d,
                    "timestamp": ts,
                    "display_time": "09:00 AM",
                    "picks_count": len(formatted),
                    "picks": formatted,
                })
        if records:
            os.makedirs(os.path.dirname(DAILY_PICKS_JSON_PATH) or ".", exist_ok=True)
            with open(DAILY_PICKS_JSON_PATH, "w", encoding="utf-8") as f:
                json.dump(records, f, indent=2)
    except Exception as e:
        logger.warning("Failed bootstrapping history from DB: %s", e)

    return records



def _attach_price_validation(candidates: list[dict]) -> tuple[list[dict], list[dict]]:
    from modules.price_validation import validate_price

    accepted = []
    rejected = []
    for stock in candidates:
        validation = validate_price(stock["symbol"], stock.get("entry_price") or stock.get("price"))
        enriched = {
            **stock,
            "price_validation": validation,
            "validated_price": validation.get("consensus_price"),
            "price_validation_status": validation.get("status"),
        }
        if validation.get("status") == "passed":
            if validation.get("consensus_price"):
                enriched["entry_price"] = round(validation["consensus_price"], 2)
            accepted.append(enriched)
        else:
            enriched["reject_reason"] = f"price validation: {validation.get('details')}"
            rejected.append(enriched)
    return accepted, rejected


def _grok_review_evidence_pack(candidates: list[dict], rejected: list[dict]) -> str:
    try:
        from modules.grok_brain import review_event
    except Exception:
        return ""

    evidence = []
    for c in candidates[:20]:
        edge = c.get("edge", {})
        validation = c.get("price_validation", {})
        evidence.append({
            "symbol": c.get("symbol"),
            "score": c.get("score"),
            "pattern_key": c.get("pattern_key"),
            "edge_status": c.get("edge_status"),
            "hit_rate": edge.get("hit_rate"),
            "backtest_trades": edge.get("total_trades"),
            "avg_return": edge.get("avg_return"),
            "price_validation": validation.get("status"),
            "sources_ok": validation.get("sources_ok"),
            "spread_pct": validation.get("spread_pct"),
            "rsi": c.get("rsi"),
            "ema_alignment": c.get("ema_alignment"),
            "vol_ratio": c.get("vol_ratio"),
            "prime_window": c.get("prime_window"),
            "target_return_pct": c.get("target_return_pct"),
            "timing_strategy": c.get("timing_strategy"),
            "signal_reasons": c.get("signal_reasons"),
        })

    review = review_event(
        "top20_candidate_evidence_before_final_picks",
        {
            "candidate_count": len(candidates),
            "rejected_count": len(rejected),
            "intraday_return_target": "5.0% - 8.0% return in specific intraday market period",
            "evidence": evidence,
            "rejected_summary": [
                {
                    "symbol": r.get("symbol"),
                    "reason": r.get("reject_reason") or r.get("edge_reject_reason"),
                    "pattern_key": r.get("pattern_key"),
                }
                for r in rejected[:20]
            ],
        },
    )
    if not review.get("ok"):
        return ""

    summary = (
        f"Verdict={review.get('verdict', 'reviewed')}; "
        f"Risk={review.get('risk_level', 'unknown')}; "
        f"Review={review.get('brief_review', '')}; "
        f"Next={review.get('next_action', '')}"
    )[:900]

    try:
        from config import DB_PATH
        from modules.db_migrations import ensure_research_tables

        ensure_research_tables()
        with sqlite3.connect(DB_PATH) as conn:
            conn.execute(
                """INSERT INTO grok_evidence_reviews
                   (date, event_type, candidate_count, verdict, risk_level,
                    brief_review, next_action, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    today_ist_str(),
                    "top20_candidate_evidence_before_final_picks",
                    len(candidates),
                    str(review.get("verdict", ""))[:80],
                    str(review.get("risk_level", ""))[:40],
                    str(review.get("brief_review", ""))[:500],
                    str(review.get("next_action", ""))[:300],
                    now_ist().isoformat(timespec="seconds"),
                ),
            )
            conn.commit()
    except Exception as e:
        logger.debug("Could not persist Grok evidence review: %s", e)

    return summary


def _compute_correlation_matrix(candidates: list[dict]) -> dict[tuple[str, str], float]:
    """
    Computes pairwise Pearson correlation of daily percentage returns for candidate stocks.
    Uses batch download without artificial sleep for zero latency penalty.
    Returns a dict mapping (sym_a, sym_b) -> correlation_float.
    """
    import numpy as np
    import pandas as pd

    symbols = [str(c.get("symbol", "")).upper().strip() for c in candidates if c.get("symbol")]
    if len(symbols) < 2:
        return {}

    returns_by_sym: dict[str, pd.Series] = {}

    for c in candidates:
        sym = str(c.get("symbol", "")).upper().strip()
        if not sym:
            continue
        if "returns" in c and isinstance(c["returns"], (pd.Series, list, np.ndarray)) and len(c["returns"]) >= 5:
            returns_by_sym[sym] = pd.Series(c["returns"]).dropna()

    missing_syms = [s for s in symbols if s not in returns_by_sym]
    if len(missing_syms) >= 1 and (len(returns_by_sym) + len(missing_syms) >= 2):
        try:
            import yfinance as yf
            tickers = [f"{s}.NS" for s in missing_syms]
            batch_df = yf.download(
                tickers=tickers,
                period="1mo",
                interval="1d",
                progress=False,
                group_by="ticker",
                auto_adjust=True,
                threads=True,
                timeout=8,
            )
            if batch_df is not None and not batch_df.empty:
                for sym in missing_syms:
                    ticker = f"{sym}.NS"
                    try:
                        if isinstance(batch_df.columns, pd.MultiIndex):
                            df = batch_df[ticker] if ticker in batch_df else None
                        else:
                            df = batch_df
                        if df is None or df.empty:
                            continue
                        close_col = df["Close"] if "Close" in df.columns else df.get("close")
                        if close_col is not None:
                            s = close_col.dropna()
                            if len(s) >= 5:
                                rets = s.pct_change().dropna()
                                if len(rets) >= 4:
                                    returns_by_sym[sym] = rets
                    except Exception:
                        pass
        except Exception as e:
            logger.debug("Picker correlation batch download skipped/failed: %s", e)

    corr_matrix: dict[tuple[str, str], float] = {}
    calc_syms = list(returns_by_sym.keys())
    for i in range(len(calc_syms)):
        s1 = calc_syms[i]
        r1 = returns_by_sym[s1]
        for j in range(i + 1, len(calc_syms)):
            s2 = calc_syms[j]
            r2 = returns_by_sym[s2]
            try:
                aligned1, aligned2 = r1.align(r2, join="inner")
                if len(aligned1) >= 5:
                    v1 = aligned1.values.astype(float)
                    v2 = aligned2.values.astype(float)
                elif len(r1) >= 5 and len(r2) >= 5:
                    min_len = min(len(r1), len(r2))
                    v1 = r1.iloc[-min_len:].values.astype(float)
                    v2 = r2.iloc[-min_len:].values.astype(float)
                else:
                    continue
                if np.std(v1) > 1e-9 and np.std(v2) > 1e-9:
                    with np.errstate(all='ignore'):
                        c_matrix = np.corrcoef(v1, v2)
                        corr_val = float(c_matrix[0, 1])
                        if not np.isnan(corr_val):
                            corr_matrix[(s1, s2)] = round(corr_val, 4)
                            corr_matrix[(s2, s1)] = round(corr_val, 4)
            except Exception:
                pass

    return corr_matrix


def run_picker(analyzed: list = None) -> list:
    """
    Main picker pipeline.
    1. Takes analyzer output (or runs analyzer if not provided)
    2. Filters by risk-reward
    3. Diversifies via cross-stock correlation gate (anti-concentration)
    4. Returns top-5 picks
    5. Writes to DB
    """
    from config import TOP_N_PICKS
    from modules.db_migrations import ensure_research_tables
    from modules.quality_gates import audit_candidate, data_quality_snapshot, enrich_candidate

    ensure_research_tables()
    data_quality = data_quality_snapshot("picker_start")

    if analyzed is None:
        from modules.analyzer import analyze_all
        analyzed = analyze_all()

    if not analyzed:
        logger.warning("No analyzed stocks available for picker")
        return []

    # Take top 20 by score
    candidates = analyzed[:20]
    logger.info(f"Picker evaluating {len(candidates)} candidates")
    for stock in candidates:
        audit_candidate("candidate_pool", stock, True, "entered_top20_picker_pool")

    # Apply risk-reward filter
    valid = []
    for stock in candidates:
        result = _calculate_levels(stock)
        if result:
            valid.append(result)
            audit_candidate("risk_reward", result, True, "rr_passed")
        else:
            audit_candidate("risk_reward", stock, False, "rr_below_minimum_or_invalid_levels")

    if not valid:
        logger.warning("No picks passed risk-reward filter")
        return []

    # Cross-check price from Yahoo + NSE + broker if configured.
    valid, price_rejected = _attach_price_validation(valid)
    for item in valid:
        audit_candidate("price_validation", item, True, "price_validation_passed")
    for item in price_rejected:
        audit_candidate("price_validation", item, False, item.get("reject_reason", "price_validation_failed"))
    if not valid:
        logger.warning("No picks passed cross-source price validation: %s", len(price_rejected))
        return []

    # Only allow patterns with proven edge in the backtest table.
    from modules.pattern_backtester import filter_candidates_by_edge
    valid, edge_rejected = filter_candidates_by_edge(valid)
    rejected = price_rejected + edge_rejected
    for item in valid:
        audit_candidate("pattern_edge", item, True, "proven_edge_passed")
    for item in edge_rejected:
        audit_candidate("pattern_edge", item, False, item.get("edge_reject_reason", "proven_edge_failed"))
    if not valid:
        logger.warning("No picks passed proven-edge pattern gate: %s rejected", len(rejected))
        return []

    grok_review = _grok_review_evidence_pack(valid, rejected)
    if grok_review:
        for item in valid:
            item["grok_review"] = grok_review

    try:
        from modules.market_terminal import rank_candidates

        valid = rank_candidates(valid)
        for item in valid:
            item["score"] = item.get("terminal_score", item.get("score", 0))
    except Exception as exc:
        logger.debug("Terminal ranking skipped in picker: %s", exc)
        valid.sort(key=lambda x: x["score"], reverse=True)

    enriched_valid = []
    for item in valid:
        enriched = enrich_candidate(item, data_quality=data_quality)
        enriched_valid.append(enriched)
        audit_candidate("quality_scoring", enriched, True, enriched.get("quality_reasons", "quality_scored"))
    valid = sorted(enriched_valid, key=lambda x: x.get("score", 0), reverse=True)

    # Feature 3: Cross-Stock Correlation Gate (Greedy Anti-Concentration)
    corr_matrix = _compute_correlation_matrix(valid)
    CORR_THRESHOLD = 0.70

    top_picks: list[dict] = []
    skipped_by_gate: list[tuple[dict, str]] = []

    for item in valid:
        if len(top_picks) >= TOP_N_PICKS:
            break
        sym = str(item.get("symbol", "")).upper().strip()
        sec = item.get("sector")

        is_correlated = False
        reason = ""

        sec_count = sum(1 for p in top_picks if p.get("sector") == sec and sec not in ("Unknown", "", None))
        if sec_count >= 2:
            is_correlated = True
            reason = f"sector_gate: {sym} sector cap reached ({sec}: max 2 picks)"
        else:
            for picked in top_picks:
                p_sym = str(picked.get("symbol", "")).upper().strip()

                # 1. Pearson correlation check if available
                if (sym, p_sym) in corr_matrix:
                    pair_corr = corr_matrix[(sym, p_sym)]
                    if pair_corr > CORR_THRESHOLD:
                        is_correlated = True
                        reason = f"corr_gate: {sym} correlated with {p_sym} (r={pair_corr:.2f} > {CORR_THRESHOLD})"
                        break

        if is_correlated:
            logger.info("Anti-concentration gate skipped %s: %s", sym, reason)
            skipped_by_gate.append((item, reason))
        else:
            top_picks.append(item)

    # Fewer picks is a valid result. Rejected correlated candidates stay rejected.

    selected_symbols = {p.get("symbol") for p in top_picks}
    for item in valid:
        sym = item.get("symbol")
        if sym not in selected_symbols:
            gate_reason = next((r for cand, r in skipped_by_gate if cand.get("symbol") == sym), None)
            if gate_reason:
                audit_candidate("anti_concentration", item, False, gate_reason)
            audit_candidate("final_selection", item, False, f"ranked_below_top{TOP_N_PICKS}_or_correlated")

    for i, pick in enumerate(top_picks, start=1):
        pick["rank"] = i
        audit_candidate("final_selection", pick, True, f"selected_rank_{i}")

    # Write to DB
    _write_picks_to_db(top_picks)

    logger.info(f"Final picks: {[p['symbol'] for p in top_picks]}")
    return top_picks


def get_todays_picks() -> list:
    """Fetch today's picks from DB."""
    from config import DB_PATH
    today = today_ist_str()
    with sqlite3.connect(DB_PATH) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute(
            "SELECT * FROM picks WHERE date=? AND COALESCE(session_type, 'morning_final')='morning_final' "
            "AND COALESCE(is_official_morning, 1)=1 ORDER BY rank",
            (today,),
        ).fetchall()
    return [dict(r) for r in rows]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    picks = run_picker()
    for p in picks:
        print(f"#{p['rank']} {p['symbol']:12} Entry={p['entry_price']:.2f}  "
              f"SL={p['sl_price']:.2f}  Target={p['target_price']:.2f}  "
              f"RR={p['risk_reward']:.1f}  Score={p['score']:.1f}")
