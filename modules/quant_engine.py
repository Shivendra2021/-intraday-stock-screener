"""Quant v3 orchestrator: watchlist -> point-in-time signals -> paper outcomes.

Only this engine publishes v3 picks. Legacy agents remain available for research
but cannot backfill or override a rejected v3 candidate.
"""
from __future__ import annotations

import datetime as dt
import html
import json
import logging
import time

import pandas as pd

from modules.quant_data import DataService, universe
from modules.quant_features import build_features, daily_features, gate, quote_gate
from modules.quant_learning import active_model, shadow_model, predict, train, metrics
from modules.quant_outcomes import evaluate
from modules.quant_store import Store, dumps
from modules.quant_time import now_ist

LOG = logging.getLogger(__name__)


def _clock(value):
    return dt.time.fromisoformat(value)


def prepare(store=None, service=None, now=None, budget=None):
    from config import QUANT_PREPARE_BUDGET_SECONDS, QUANT_WATCHLIST_SIZE, QUANT_MIN_DAILY_VALUE, QUANT_HISTORY_DAYS
    store = store or Store(); service = service or DataService(store); now = now or now_ist()
    budget = QUANT_PREPARE_BUDGET_SECONDS if budget is None else budget
    started = time.monotonic()
    with store.lease("prepare", budget * 2 + 120) as acquired:
        if not acquired:
            return {"status": "busy"}
        symbols = universe()
        # Resume from last incomplete daily pass; never permanently omit tail symbols.
        cursor = int(store.get("daily_cursor", 0)) % max(1, len(symbols))
        ordered = list(symbols)[cursor:] + list(symbols)[:cursor]
        health = service.refresh(ordered, "1d", "1y", budget=budget)
        store.put("daily_cursor", (cursor + health["updated"] + health["failed"] + health["cache_hits"]) % max(1, len(symbols)))
        bases, watch = {}, []
        for symbol, sector in symbols.items():
            frame = store.bars(symbol, "1d")
            base = daily_features(frame, now.date())
            if base:
                bases[symbol] = {**base, "sector": sector}
                if base["turnover"] >= QUANT_MIN_DAILY_VALUE and base["prev_close"] >= 20:
                    score = min(base["atr_pct"], 8)*8 + max(-15, min(base["daily_trend"], 10))
                    watch.append({"symbol": symbol, "sector": sector, "score": round(score, 2), **base})
        watch.sort(key=lambda r: r["score"], reverse=True)
        watch = watch[:QUANT_WATCHLIST_SIZE]
        store.put("daily_features", {"date": str(now.date()), "symbols": bases})
        store.put("watchlist", {"date": str(now.date()), "created_at": now.isoformat(), "candidates": watch,
                                "status": "ready" if watch else "waiting_for_history", "coverage": len(bases),
                                "universe_size": len(symbols), "purpose": "Pre-market research; no entries yet"})
        history = service.refresh([r["symbol"] for r in watch], "5m", f"{QUANT_HISTORY_DAYS}d", budget=budget)
        result = {"status": "prepared" if watch else "waiting_for_history", "watchlist_count": len(watch),
                  "daily": health, "intraday": history, "elapsed_seconds": round(time.monotonic()-started, 3)}
        store.put("preparation", result)
        return result


def replay(store=None, symbols=None, budget=900):
    from config import QUANT_CONFIRM_START, QUANT_ENTRY_CUTOFF
    store = store or Store()
    if symbols is None:
        with store.connect() as c:
            symbols = [r[0] for r in c.execute("SELECT DISTINCT symbol FROM bars WHERE interval='5m'")]
        cursor = int(store.get("replay_cursor", 0)) % max(1, len(symbols))
        symbols = symbols[cursor:] + symbols[:cursor]
    else:
        cursor = None
    start = time.monotonic(); count = resolved = 0
    sectors = universe()
    today = now_ist().date()
    with store.lease("replay", budget + 120) as acquired:
        if not acquired:
            return {"status": "busy"}
        completed_symbols = 0
        for index, symbol in enumerate(symbols):
            if time.monotonic() - start > budget:
                break
            if cursor is not None:
                store.put("replay_cursor", (cursor + index + 1) % max(1, len(symbols)))
            daily, bars = store.bars(symbol, "1d"), store.bars(symbol, "5m")
            dates = sorted(set(bars.index.date))
            for date in dates:
                if date >= today or time.monotonic()-start > budget:
                    break
                if store.get(f"replayed:{symbol}:{date}"):
                    continue
                base = daily_features(daily, date)
                if not base:
                    continue
                day = bars[bars.index.date == date]
                records = []
                for idx in day.index:
                    asof = idx + pd.Timedelta(minutes=5)
                    if not _clock(QUANT_CONFIRM_START) <= asof.time() <= _clock(QUANT_ENTRY_CUTOFF):
                        continue
                    row = build_features(symbol, daily, bars, asof, sectors.get(symbol, "Unknown"), base)
                    if row:
                        outcome = evaluate(row, bars)
                        records.append((row, gate(row), outcome))
                        count += 1
                        resolved += int(outcome["resolved"])
                # Mark only complete sessions; missing sessions can be repaired.
                store.save_replay(records)
                if len(day) == 75 and records and all(r[2]["resolved"] for r in records):
                    store.put(f"replayed:{symbol}:{date}", True)
            completed_symbols += 1
        result = {"status": "replayed", "observations": count, "resolved": resolved,
                  "visited_symbols": completed_symbols, "available_symbols": len(symbols),
                  "budget_exhausted": time.monotonic()-start > budget,
                  "elapsed_seconds": round(time.monotonic()-start, 3),
                  "limitation": "Available current-universe history; historical eligibility/depth not verified."}
        store.put("replay", result)
        return result


def reconcile(store=None, now=None):
    """Reconcile every observation including rejected setups; no current-day highs before entry."""
    from config import QUANT_EXIT_TIME
    store = store or Store(); now = now or now_ist()
    with store.connect() as c:
        rows = c.execute("SELECT o.id,o.features,t.value AS previous FROM observations o LEFT JOIN outcomes t ON o.id=t.observation_id "
                         "LEFT JOIN signals s ON s.id=o.id WHERE (t.resolved IS NULL OR t.resolved=0) "
                         "AND (o.provenance='live' OR s.id IS NOT NULL) ORDER BY (s.id IS NOT NULL) DESC,o.ts DESC LIMIT 20000").fetchall()
    bars_cache = {}; signals = {s["id"]: s for s in store.signals()}; settled = 0

    # Bounded 1m refresh for active signals
    active_symbols = list({signals[rec["id"]]["value"]["symbol"] for rec in rows if rec["id"] in signals and "value" in signals[rec["id"]] and "symbol" in signals[rec["id"]]["value"]})
    if active_symbols:
        try:
            service = DataService(store)
            service.refresh_1m(active_symbols, budget=15)
        except Exception as exc:
            LOG.debug("1m refresh failed: %s", exc)

    for rec in rows:
        original = json.loads(rec["features"])
        row = signals.get(rec["id"], {}).get("value", original)
        symbol = row["symbol"]
        if symbol not in bars_cache:
            frame = store.bars(symbol, "5m")
            bars_cache[symbol] = frame[frame.index + pd.Timedelta(minutes=5) <= now]

        # Use 1-minute execution resolution if available and covers entry bar
        bars_1m = store.bars(symbol, "1m")
        if not bars_1m.empty:
            valid_1m = bars_1m[bars_1m.index + pd.Timedelta(minutes=1) <= now]
            entry_ts = int(row.get("entry_ts", row["ts"] + 60))
            if any(int(idx.timestamp()) == entry_ts for idx in valid_1m.index):
                outcome = evaluate(row, valid_1m, cutoff=QUANT_EXIT_TIME, interval="1m")
            else:
                outcome = evaluate(row, bars_cache[symbol], cutoff=QUANT_EXIT_TIME, interval="5m")
        else:
            outcome = evaluate(row, bars_cache[symbol], cutoff=QUANT_EXIT_TIME, interval="5m")

        if dumps(outcome) != rec["previous"]:
            store.outcome(rec["id"], outcome)
        settled += int(outcome["resolved"])
    _sync_legacy(store)
    return {"checked": len(rows), "resolved": settled}


def _sync_legacy(store):
    """Mirror v3 signals transactionally into existing dashboard tables, with stable IDs."""
    import sqlite3
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables
    ensure_research_tables()
    for s in store.signals():
        p = s["value"]
        with sqlite3.connect(DB_PATH, timeout=15) as c:
            c.execute("BEGIN IMMEDIATE")
            found = c.execute("SELECT id FROM picks WHERE source_label=?", ("quant_v3:"+s["id"],)).fetchone()
            if found:
                pick_id = found[0]
            else:
                rank = c.execute("SELECT COUNT(*) FROM picks WHERE date=? AND source_label LIKE 'quant_v3:%'", (s["date"],)).fetchone()[0]+1
                cur = c.execute("""INSERT INTO picks(date,rank,symbol,entry_price,sl_price,target_price,confidence,
                    signal_reasons,status,created_at,session_type,is_official_morning,source_label,
                    price_validation_status,validated_price,edge_status,quality_reasons)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
                    s["date"], rank, s["symbol"], p["price"], p["stop"], p["price"]*1.10,
                    round(p["p7"]*100, 2), f"{p['setup']}; 7%/10% from simulated entry; half exits at each target",
                    "pending", dt.datetime.fromtimestamp(p["ts"], dt.timezone.utc).isoformat(),
                    "quant_v3_intraday", 0, "quant_v3:"+s["id"], "passed", p["quote"]["ask"],
                    "historical_holdout_only", "Simulated research; p7 is not a guarantee"))
                pick_id = cur.lastrowid
            with store.connect() as qc:
                out = qc.execute("SELECT value FROM outcomes WHERE observation_id=? AND resolved=1", (s["id"],)).fetchone()
            if out:
                o = json.loads(out[0])
                status = {"target_exit": "tp_hit", "stop_exit": "sl_hit", "eod_exit": "eod_closed",
                          "unfilled": "unfilled"}.get(o["status"], "unresolved")
                c.execute("UPDATE picks SET status=?,result_return=?,entry_price=?,target_price=? WHERE id=?",
                          (status, o.get("return_pct"), o.get("entry", p["price"]), o.get("entry", p["price"])*1.10, pick_id))
        with store.connect() as c:
            c.execute("UPDATE signals SET pick_id=? WHERE id=?", (pick_id, s["id"]))


def deliver(store=None):
    """Durable outbox; retries failed alerts without creating new selections."""
    from modules.alerts import send_raw_alert
    from config import DRY_RUN
    store = store or Store()
    if DRY_RUN:
        return {"status": "dry_run", "delivered": 0}
    sent = 0
    for signal in store.signals(str(now_ist().date())):
        if signal["notified"]:
            continue
        p = signal["value"]
        entry_time = pd.Timestamp(p.get("entry_target_ts") or p["entry_ts"], unit="s", tz="UTC").tz_convert("Asia/Kolkata").strftime("%H:%M")
        tp1 = p.get("tp1") or round(p.get("validated_price", p["price"]) * 1.07, 2)
        tp2 = p.get("tp2") or round(p.get("validated_price", p["price"]) * 1.10, 2)
        p7_pct = p.get("p7", 0.0)
        p10_pct = p.get("p10", 0.0)
        net_ret = p.get("expected_net_pct", 0.0)
        regime = p.get("market_regime", "N/A")
        sector = p.get("sector_context") or p.get("sector", "Unknown")
        quote_src = p.get("provider", "primary")

        text = (f"<b>QUANT V4 — QUALIFIED NSE CANDIDATE</b>\n"
                f"<b>{html.escape(signal['symbol'])}</b> | Setup: <code>{html.escape(p.get('reason') or p.get('setup', 'breakout'))}</code>\n"
                f"Reference: ₹{p.get('reference_price', p['price']):.2f} | Validated: ₹{p.get('validated_price', p['price']):.2f}\n"
                f"Structural Stop: ₹{p.get('structural_stop', p['stop']):.2f}\n"
                f"Target 1 (+7%): ₹{tp1:.2f} | Target 2 (+10%): ₹{tp2:.2f}\n"
                f"Simulated entry: first eligible {entry_time} bar; cancel on >1% gap.\n"
                f"Estimated P(+7%): {p7_pct:.0%} | P(+10%): {p10_pct:.0%}\n"
                f"Expected net: {net_ret:+.2f}% | RVOL: {p.get('rvol', 1.0):.2f}x\n"
                f"Regime: {html.escape(str(regime))} | Sector: {html.escape(str(sector))}\n"
                f"Quote Source: {html.escape(str(quote_src))}\n"
                f"<i>Research simulation only. Max 3 disciplined picks. No orders placed.</i>")
        if now_ist().timestamp() >= (p.get("entry_target_ts") or p["entry_ts"]):
            text = "<b>DELAYED DELIVERY — HISTORICAL SIGNAL, DO NOT CHASE</b>\n" + text
        audit_details = f"signal_id={signal['id']} symbol={signal['symbol']} p7={p7_pct:.2f}"
        if send_raw_alert(text, review_with_grok=False, event_type="quant_signal", details=audit_details):
            with store.connect() as c:
                c.execute("UPDATE signals SET notified=1 WHERE id=?", (signal["id"],))
            sent += 1
    return {"delivered": sent}


def cycle(store=None, service=None, now=None, notify=False, refresh=True):
    from config import (QUANT_CONFIRM_START, QUANT_ENTRY_CUTOFF, QUANT_EXIT_TIME, QUANT_MAX_PICKS,
                        QUANT_BROAD_BATCH_SIZE, QUANT_MIN_P7, QUANT_BAR_MAX_AGE_SECONDS)
    store = store or Store(); service = service or DataService(store); now = now or now_ist()
    started = time.monotonic(); today = str(now.date())
    with store.lease("cycle", 300) as acquired:
        if not acquired:
            return {"status": "busy"}
        watch = store.get("watchlist", {})
        if watch.get("date") != today:
            result = {"status": "waiting_for_preparation", "date": today, "candidates": []}
            store.put("runtime", result)
            return result
        all_symbols = list(universe())
        offset = int(store.get("broad_cursor", 0)) % max(1, len(all_symbols))
        broad = (all_symbols[offset:] + all_symbols[:offset])[:QUANT_BROAD_BATCH_SIZE]
        signals = store.signals(today)
        with store.connect() as c:
            outstanding = [r[0] for r in c.execute("SELECT DISTINCT s.symbol FROM signals s LEFT JOIN outcomes t ON s.id=t.observation_id WHERE t.resolved IS NULL OR t.resolved=0")]
        symbols = list(dict.fromkeys(outstanding + [r["symbol"] for r in watch.get("candidates", [])] + broad + [r["symbol"] for r in signals]))
        health = service.refresh(symbols, budget=75) if refresh else {}
        store.put("broad_cursor", (offset + len(broad)) % max(1, len(all_symbols)))
        
        # Point-in-time Market Regime Context
        from modules.market_regime import compute_market_regime, compute_sector_metrics, get_latest_market_regime, get_latest_sector_snapshots
        from modules.rejection_audit import record_rejection, get_funnel_summary
        from modules.cost_model import COST_MODEL_VERSION
        from modules.slippage_model import SLIPPAGE_MODEL_VERSION
        from modules.catalyst_engine import get_point_in_time_catalysts
        from modules.winner_discovery import get_winner_discovery_report
        from modules.experiment_registry import list_experiments

        regime_info = compute_market_regime(store, now, provenance="live")
        market_regime_label = regime_info.get("regime_label", "MIXED")
        regime_snapshot_ts = regime_info.get("ts", int(now.timestamp()))

        model = active_model(store, today)
        shadow = None if model else shadow_model(store, today)
        scoring_model = model or shadow
        prepared_state = store.get("daily_features", {})
        prepared = prepared_state.get("symbols", {}) if prepared_state.get("date") == today else {}
        ranked, rejected = [], {}
        stock_returns = {}
        start, end = _clock(QUANT_CONFIRM_START), _clock(QUANT_ENTRY_CUTOFF)
        in_window = now.weekday() < 5 and start <= now.time() <= end
        for symbol in symbols:
            base = prepared.get(symbol)
            if not base:
                rejected["history_unavailable"] = rejected.get("history_unavailable", 0)+1
                record_rejection(store, symbol, stage="history_valid", reason="history_unavailable",
                                 details={"date": today}, date=today, ts=int(now.timestamp()),
                                 feature_version="q4.0", provenance="live")
                continue
            bars = store.bars(symbol, "5m")
            row = build_features(symbol, pd.DataFrame(), bars, now, base.get("sector", "Unknown"), base)
            if not row:
                rejected["incomplete_session_or_volume_history"] = rejected.get("incomplete_session_or_volume_history", 0)+1
                record_rejection(store, symbol, stage="intraday_context", reason="incomplete_session_or_volume_history",
                                 details={"date": today}, date=today, ts=int(now.timestamp()),
                                 feature_version="q4.0", provenance="live")
                continue
            reason = gate(row)
            observed_time = dt.datetime.fromtimestamp(row["ts"], now.tzinfo).time()
            if not start <= observed_time <= end:
                record_rejection(store, symbol, stage="intraday_context", reason="outside_entry_window",
                                 details={"observed_time": str(observed_time)}, date=today, ts=int(row["ts"]),
                                 feature_version=str(row.get("feature_version", "q4.0")), provenance="live")
                continue
            if now.timestamp() - row["ts"] > QUANT_BAR_MAX_AGE_SECONDS:
                reason = "stale_candles"
            ident = store.observe(row, reason)
            row["observation_id"] = ident
            if reason != "eligible":
                rejected[reason] = rejected.get(reason, 0)+1
                stg = "rvol_gate" if "rvol" in reason else ("structural_risk" if "stop" in reason else ("universe" if "liquidity" in reason else "setup_trigger"))
                record_rejection(store, symbol, stage=stg, reason=reason,
                                 details={"price": row.get("price"), "rvol": row.get("rvol")}, date=today, ts=int(row["ts"]),
                                 feature_version=str(row.get("feature_version", "q4.0")), provenance="live")
                continue
            prev_close = float(row.get("prev_close") or base.get("prev_close") or row.get("price") or 1.0)
            stock_returns[symbol] = round((row["price"] / prev_close - 1) * 100, 2)
            ranked.append(row)

        # Context-only Sector rankings (does not affect ML weights)
        try:
            sector_rankings = compute_sector_metrics(store, now, stock_returns, universe())
            for r in ranked:
                sec = r.get("sector", "Unknown")
                sec_info = sector_rankings.get(sec, {})
                r["sector_return_15m"] = sec_info.get("return_15m", 0.0)
                r["sector_rank"] = sec_info.get("sector_rank", 99)
                r["stock_vs_sector"] = round(stock_returns.get(r["symbol"], 0.0) - sec_info.get("return_15m", 0.0), 2)
                r["market_regime"] = market_regime_label
                r["regime_snapshot_ts"] = regime_snapshot_ts
        except Exception as exc:
            LOG.debug("Sector metric calculation error: %s", exc)

        ranked = predict(scoring_model, ranked) if scoring_model else [{**r, "p7": None, "p10": None,
                                                        "expected_net_pct": None, "evidence": "unvalidated_watch_only"} for r in ranked]
        if shadow:
            ranked = [{**row, "evidence": "shadow_model_not_alert_eligible"} for row in ranked]
        ranked.sort(key=lambda r: (r.get("p7") or 0, r["baseline_score"]), reverse=True)
        used = {s["symbol"] for s in signals}
        used_sectors = {s["value"].get("sector") for s in signals if s["value"].get("sector") != "Unknown"}
        # Resolve stops from this refresh BEFORE considering another entry.
        reconcile(store, now_ist() if refresh else now)
        # Count losses from the authoritative paper ledger; research continues after losses.
        with store.connect() as c:
            losses = c.execute("SELECT t.value FROM signals s JOIN outcomes t ON s.id=t.observation_id WHERE s.date=? AND t.resolved=1", (today,)).fetchall()
        loss_count = sum((json.loads(r[0]).get("return_pct") or 0) < 0 for r in losses)
        from modules.circuit_breaker import is_circuit_breaker_active
        cb_active = is_circuit_breaker_active()
        halt_trading = cb_active or (loss_count >= 2)
        from modules.quant_review import review as review_candidate
        watch_candidates, quote_failures = [], 0
        market_context = store.get("dashboard_market", {})
        for row in ranked[:10]:
            row["entry_ts"] = row["ts"] + 300
            quote, secondary_quote, reason = None, None, None
            if not model:
                reason = "model_collecting_evidence"
                record_rejection(store, row["symbol"], stage="model_gate", reason=reason,
                                 date=today, ts=int(row["ts"]), model_version=str(scoring_model.get("id") if scoring_model else "none"),
                                 feature_version=str(row.get("feature_version", "q4.0")), provenance="live")
            elif not in_window:
                reason = "outside_confirmation_window"
                record_rejection(store, row["symbol"], stage="intraday_context", reason=reason,
                                 date=today, ts=int(row["ts"]), provenance="live")
            elif row["symbol"] in used or (row["sector"] != "Unknown" and row["sector"] in used_sectors):
                reason = "duplicate_symbol_or_sector"
                record_rejection(store, row["symbol"], stage="selected", reason=reason,
                                 date=today, ts=int(row["ts"]), provenance="live")
            elif row["p7"] < QUANT_MIN_P7 or row["expected_net_pct"] <= 0:
                reason = "insufficient_model_edge"
                record_rejection(store, row["symbol"], stage="expected_return", reason=reason,
                                 details={"p7": row.get("p7"), "expected_net_pct": row.get("expected_net_pct")},
                                 date=today, ts=int(row["ts"]), model_version=str(scoring_model.get("id") if scoring_model else "none"),
                                 provenance="live")
            elif len(used) >= QUANT_MAX_PICKS:
                reason = "qualified_slots_full"
                record_rejection(store, row["symbol"], stage="selected", reason=reason,
                                 date=today, ts=int(row["ts"]), provenance="live")
            elif halt_trading:
                reason = "circuit_breaker_halt" if cb_active else "daily_loss_guard"
                record_rejection(store, row["symbol"], stage="selected", reason=reason,
                                 date=today, ts=int(row["ts"]), provenance="live")
            else:
                if hasattr(service, "get_quote_candidates"):
                    quote, secondary_quote = service.get_quote_candidates(row["symbol"])
                else:
                    quote = service.quote(row["symbol"])
                    secondary_quote = None
                checked_now = now_ist() if refresh else now
                reason = quote_gate(row, quote, checked_now, secondary_quote=secondary_quote)
                if checked_now.timestamp() >= row["entry_ts"]:
                    reason = "entry_window_elapsed"
                if reason != "eligible":
                    quote_failures += 1
                    record_rejection(store, row["symbol"], stage="quote_verified", reason=reason,
                                     details={"primary": quote.get("source") if quote else None,
                                              "secondary": secondary_quote.get("source") if secondary_quote else None,
                                              "consensus_status": row.get("consensus_status")},
                                     date=today, ts=int(row["ts"]), provenance="live")
            candidate_review = review_candidate(row, model_ready=bool(model), quote_reason=reason,
                                                loss_count=loss_count, selected=len(used), in_window=in_window,
                                                market_context=market_context)
            row["review"] = candidate_review
            row["rejection"] = candidate_review["reason"]
            store.record_review(row["observation_id"], row, candidate_review["decision"], candidate_review)
            if candidate_review["decision"] == "watchlist" and len(watch_candidates) < QUANT_MAX_PICKS:
                watch_candidates.append(row)
            if candidate_review["decision"] != "qualified":
                continue
            ref_px = float(row["price"])
            val_px = float(quote.get("ask", ref_px))
            bid_px = float(quote.get("bid", 0.0))
            ask_px = float(quote.get("ask", val_px))
            spread_amt = max(0.0, ask_px - bid_px) if bid_px > 0 else 0.0
            spread_pct = round((spread_amt / ask_px) * 100, 4) if ask_px > 0 else 0.0
            entry_target_ts = int(row.get("entry_ts", row["ts"] + 300))

            # Point-in-time external catalysts strictly before decision_ts
            catalysts = get_point_in_time_catalysts(row["symbol"], decision_ts=int(row["ts"]), store=store)
            row["catalyst_flags"] = catalysts

            signal = {
                "signal_id": row["observation_id"],
                "symbol": row["symbol"],
                "date": today,
                "decision_ts": int(row["ts"]),
                "feature_snapshot_ts": int(row["ts"]),
                "entry_target_ts": entry_target_ts,
                "reference_price": round(ref_px, 2),
                "validated_price": round(val_px, 2),
                "bid": round(bid_px, 2),
                "ask": round(ask_px, 2),
                "spread": round(spread_amt, 4),
                "spread_pct": spread_pct,
                "provider": str(quote.get("source", "angel_one")),
                "secondary_provider": str(secondary_quote.get("source")) if secondary_quote else None,
                "consensus_status": str(row.get("consensus_status", "single_source_only")),
                "consensus_diff_pct": float(row.get("consensus_diff_pct", 0.0)),
                "structural_stop": round(float(row["stop"]), 2),
                "tp1": round(val_px * 1.07, 2),
                "tp2": round(val_px * 1.10, 2),
                "p7": float(row.get("p7", 0.0) or 0.0),
                "p10": float(row.get("p10", 0.0) or 0.0),
                "expected_net_pct": round(float(row.get("expected_net_pct", 0.0) or 0.0), 3),
                "feature_version": str(row.get("feature_version", "q4.0")),
                "model_id": str(scoring_model.get("id") if scoring_model else "baseline"),
                "cost_model_version": COST_MODEL_VERSION,
                "slippage_model_version": SLIPPAGE_MODEL_VERSION,
                "market_regime": str(row.get("market_regime", market_regime_label)),
                "regime_snapshot_ts": int(row.get("regime_snapshot_ts", regime_snapshot_ts)),
                "sector_context": str(row.get("sector", "Unknown")),
                "sector_rank": int(row.get("sector_rank", 99)),
                "sector_return_15m": float(row.get("sector_return_15m", 0.0)),
                "stock_vs_sector": float(row.get("stock_vs_sector", 0.0)),
                "catalyst_context": catalysts,
                "quote_validation": "passed",
                "reason": str(row.get("setup", "none")),
                "setup": str(row.get("setup", "none")),
                "price": round(ref_px, 2),
                "stop": round(float(row["stop"]), 2),
                "ts": int(row["ts"]),
                "entry_ts": entry_target_ts,
                "rvol": round(float(row.get("rvol", 1.0)), 2),
                "vwap": round(float(row.get("vwap", ref_px)), 2),
                "provenance": "quant_live_confirmed",
                "quote": quote,
                "upper": quote.get("upper"),
                "execution": "next_verified_5m_bar",
                "published_at": checked_now.isoformat()
            }
            if store.add_signal(row["observation_id"], signal):
                used.add(row["symbol"]); used_sectors.add(row["sector"])
        reconciliation = reconcile(store, now_ist() if refresh else now)
        if notify:
            deliver(store)
        status = "monitoring" if model else ("shadow_evaluation" if shadow else "backfilling")
        if not in_window:
            status = "watchlist_only" if now.time() < start else "entry_window_closed"
        if halt_trading:
            status = "circuit_breaker_halt" if cb_active else "daily_loss_guard"
        if in_window and model and ranked and not used and quote_failures:
            status = "live_quote_unavailable"
        result = {"status": status, "date": today, "updated_at": now.isoformat(), "model_id": model["id"] if model else None,
                  "shadow_model_id": shadow["id"] if shadow else None,
                  "selected": len(used), "candidates": ranked[:20], "rejections": rejected,
                  "watch_candidates": watch_candidates, "reviewed_candidates": min(len(ranked), 10),
                  "quote_failures": quote_failures,
                  "data": health, "universe_size": len(all_symbols), "evaluated_symbols": len(symbols),
                  "coverage_note": "Free source: rotating broad coverage, not a full-universe live feed.",
                  "reconciliation": reconciliation, "elapsed_seconds": round(time.monotonic()-started, 3)}
        store.put("runtime", result)
        return result


def snapshot(store=None):
    store = store or Store()
    with store.connect() as c:
        count = c.execute("SELECT COUNT(*) FROM observations").fetchone()[0]
        rows = c.execute("SELECT t.value FROM signals s JOIN outcomes t ON s.id=t.observation_id WHERE t.resolved=1").fetchall()
    outcomes = [json.loads(r[0]) for r in rows]
    filled = [r for r in outcomes if r.get("return_pct") is not None]
    today = str(now_ist().date())
    runtime = store.get("runtime", {})
    if runtime.get("date") != today:
        runtime = {"status": "awaiting_session", "date": today, "previous_run": runtime.get("updated_at")}
    signals = store.signals(today)
    with store.connect() as c:
        for s in signals:
            result = c.execute("SELECT value FROM outcomes WHERE observation_id=?", (s["id"],)).fetchone()
            s["outcome"] = json.loads(result[0]) if result else None
    from modules.rejection_audit import get_funnel_summary
    from modules.market_regime import get_latest_market_regime, get_latest_sector_snapshots
    from modules.winner_discovery import get_winner_discovery_report
    from modules.experiment_registry import list_experiments

    return {"date": today, "runtime": runtime, "watchlist": store.get("watchlist", {}),
            "learning": store.get("learning", {}), "preparation": store.get("preparation", {}),
            "data_health": store.get("data_health", {}), "quote_health": store.get("quote_health", {}), "signals": signals,
            "reviews": store.reviews(today), "qualitative_review": store.get("quant_ai_review", {}),
            "provider_audit": store.get("provider_audit", {}), "replay": store.get("replay", {}),
            "benchmark": store.get("benchmark", {}),
            "funnel": get_funnel_summary(store, today),
            "market_regime": get_latest_market_regime(store, today),
            "sector_snapshots": get_latest_sector_snapshots(store, today),
            "experiments": list_experiments(store=store),
            "winners": get_winner_discovery_report(store, today),
            "observations": count, "performance": {"filled_closed": len(filled), "unfilled": len(outcomes)-len(filled),
                "mean_net_pct": sum(r["return_pct"] for r in filled)/len(filled) if filled else None,
                "hit7_rate": sum(r["hit7"] for r in filled)/len(filled) if filled else None,
                "hit10_rate": sum(r["hit10"] for r in filled)/len(filled) if filled else None}}


def learn(store=None):
    store = store or Store()
    from config import QUANT_RESEARCH_BUDGET_SECONDS
    result = replay(store, budget=QUANT_RESEARCH_BUDGET_SECONDS)
    result["learning"] = train(store)
    store.put("last_learning_date", str(now_ist().date()))
    return result
