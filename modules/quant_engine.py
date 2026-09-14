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
    for rec in rows:
        original = json.loads(rec["features"])
        row = signals.get(rec["id"], {}).get("value", original)
        symbol = row["symbol"]
        if symbol not in bars_cache:
            frame = store.bars(symbol, "5m")
            bars_cache[symbol] = frame[frame.index + pd.Timedelta(minutes=5) <= now]
        outcome = evaluate(row, bars_cache[symbol], cutoff=QUANT_EXIT_TIME)
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
        entry_time = pd.Timestamp(p["entry_ts"], unit="s", tz="UTC").tz_convert("Asia/Kolkata").strftime("%H:%M")
        text = (f"<b>QUANT V3 — QUALIFIED NSE CANDIDATE</b>\n{html.escape(signal['symbol'])} | {html.escape(p['setup'])}\n"
                f"Reference: ₹{p['price']:.2f} | Structural stop: ₹{p['stop']:.2f}\n"
                f"Simulation entry: first eligible {entry_time} bar; cancel on >1% gap.\n"
                f"Targets from entry: +7% / +10%, half at each.\n"
                f"Estimated P(+7% before stop): {p['p7']:.0%}\nEstimated P(+10% before stop): {p['p10']:.0%}\n"
                f"Expected net: {p['expected_net_pct']:.2f}% | RVOL: {p['rvol']:.2f}x\n"
                f"<i>Historical model estimates. Informational candidate only; no order is placed.</i>")
        # An alert delivered after the simulated entry is explicitly marked late.
        if now_ist().timestamp() >= p["entry_ts"]:
            text = "<b>DELAYED DELIVERY — HISTORICAL SIGNAL, DO NOT CHASE</b>\n" + text
        if send_raw_alert(text, review_with_grok=False, event_type="quant_signal"):
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
        model = active_model(store, today)
        shadow = None if model else shadow_model(store, today)
        scoring_model = model or shadow
        prepared_state = store.get("daily_features", {})
        prepared = prepared_state.get("symbols", {}) if prepared_state.get("date") == today else {}
        ranked, rejected = [], {}
        start, end = _clock(QUANT_CONFIRM_START), _clock(QUANT_ENTRY_CUTOFF)
        in_window = now.weekday() < 5 and start <= now.time() <= end
        for symbol in symbols:
            base = prepared.get(symbol)
            if not base:
                rejected["history_unavailable"] = rejected.get("history_unavailable", 0)+1
                continue
            bars = store.bars(symbol, "5m")
            row = build_features(symbol, pd.DataFrame(), bars, now, base.get("sector", "Unknown"), base)
            if not row:
                rejected["incomplete_session_or_volume_history"] = rejected.get("incomplete_session_or_volume_history", 0)+1
                continue
            reason = gate(row)
            observed_time = dt.datetime.fromtimestamp(row["ts"], now.tzinfo).time()
            if not start <= observed_time <= end:
                continue
            if now.timestamp() - row["ts"] > QUANT_BAR_MAX_AGE_SECONDS:
                reason = "stale_candles"
            ident = store.observe(row, reason)
            row["observation_id"] = ident
            if reason != "eligible":
                rejected[reason] = rejected.get(reason, 0)+1
                continue
            ranked.append(row)
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
        from modules.quant_review import review as review_candidate
        watch_candidates, quote_failures = [], 0
        market_context = store.get("dashboard_market", {})
        for row in ranked[:10]:
            row["entry_ts"] = row["ts"] + 300
            quote, reason = None, None
            if not model:
                reason = "model_collecting_evidence"
            elif not in_window:
                reason = "outside_confirmation_window"
            elif row["symbol"] in used or (row["sector"] != "Unknown" and row["sector"] in used_sectors):
                reason = "duplicate_symbol_or_sector"
            elif row["p7"] < QUANT_MIN_P7 or row["expected_net_pct"] <= 0:
                reason = "insufficient_model_edge"
            elif len(used) >= QUANT_MAX_PICKS:
                reason = "qualified_slots_full"
            elif loss_count >= 2:
                reason = "daily_loss_guard"
            else:
                quote = service.quote(row["symbol"])
                checked_now = now_ist() if refresh else now
                reason = quote_gate(row, quote, checked_now)
                if checked_now.timestamp() >= row["entry_ts"]:
                    reason = "entry_window_elapsed"
                if reason != "eligible":
                    quote_failures += 1
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
            signal = {**row, "quote": quote, "upper": quote["upper"],
                      "execution": "next_verified_5m_bar", "published_at": checked_now.isoformat()}
            if store.add_signal(row["observation_id"], signal):
                used.add(row["symbol"]); used_sectors.add(row["sector"])
        reconciliation = reconcile(store, now_ist() if refresh else now)
        if notify:
            deliver(store)
        status = "monitoring" if model else ("shadow_evaluation" if shadow else "backfilling")
        if not in_window:
            status = "watchlist_only" if now.time() < start else "entry_window_closed"
        if loss_count >= 2:
            status = "daily_loss_guard"
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
    return {"date": today, "runtime": runtime, "watchlist": store.get("watchlist", {}),
            "learning": store.get("learning", {}), "preparation": store.get("preparation", {}),
            "data_health": store.get("data_health", {}), "quote_health": store.get("quote_health", {}), "signals": signals,
            "reviews": store.reviews(today), "qualitative_review": store.get("quant_ai_review", {}),
            "provider_audit": store.get("provider_audit", {}), "replay": store.get("replay", {}),
            "benchmark": store.get("benchmark", {}),
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
