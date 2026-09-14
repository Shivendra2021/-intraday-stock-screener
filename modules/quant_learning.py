"""Regularized probability models with date-separated calibration and evaluation.

No live exploration or daily parameter edits. A candidate is promoted only on
later sessions, with a fixed cost/exit policy and a conservative mean-return
bound. The original observation features are never re-derived after the fact.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import time

import numpy as np

from modules.quant_features import FEATURES, VERSION, gate
from modules.quant_store import dumps


def _sigmoid(z):
    return 1 / (1 + np.exp(-np.clip(z, -30, 30)))


def _fit(x, y, ridge=2.0):
    x = np.column_stack([np.ones(len(x)), x])
    w = np.zeros(x.shape[1])
    penalty = np.eye(x.shape[1]) * ridge
    penalty[0, 0] = 1e-6
    for _ in range(40):
        p = _sigmoid(x @ w)
        h = x.T @ (x * np.maximum(p * (1-p), 1e-6)[:, None]) + penalty
        step = np.linalg.solve(h, x.T @ (p-y) + penalty @ w)
        w -= step
        if np.max(np.abs(step)) < 1e-6:
            break
    return w


def predict(model, rows):
    if not rows:
        return []
    x = np.array([[r[k] for k in FEATURES] for r in rows], dtype=float)
    x = np.clip((x - np.array(model["mean"])) / np.array(model["scale"]), -8, 8)
    out = []
    probabilities = []
    for target in ("7", "10"):
        w = np.array(model["weights"][target])
        logit = w[0] + x @ w[1:]
        cal = model["calibration"][target]
        probabilities.append(_sigmoid(cal[0] + cal[1] * logit))
    for i, row in enumerate(rows):
        p7, p10 = float(probabilities[0][i]), float(probabilities[1][i])
        p10 = min(p7, p10)
        # Expected net return fitted separately; probabilities are not scores.
        rw = np.array(model["return_weights"])
        expected = float(rw[0] + x[i] @ rw[1:])
        out.append({**row, "p7": p7, "p10": p10, "expected_net_pct": expected,
                    "model_id": model["id"], "evidence": "date_holdout_paper_model"})
    return out


def portfolio(rows, baseline=False, min_p7=None):
    from config import QUANT_MIN_P7, QUANT_MAX_PICKS
    threshold = QUANT_MIN_P7 if min_p7 is None else min_p7
    # Decisions only compare candidates available at the SAME timestamp. No
    # ranking using the full day's later candidates or realized returns.
    groups = {}
    for r in rows:
        groups.setdefault((r["date"], r["ts"]), []).append(r)
    used, sectors, picks = {}, {}, []
    for (date, _), batch in sorted(groups.items()):
        selected = used.setdefault(date, set())
        selected_sectors = sectors.setdefault(date, set())
        known_losses = sum(bool(r["date"] == date and (r.get("outcome", {}).get("return_pct") or 0) < 0
                           and r["outcome"].get("fills")
                           and r["outcome"]["fills"][-1]["ts"] + 300 <= batch[0]["ts"]) for r in picks)
        if known_losses >= 2:
            continue
        key = "baseline_score" if baseline else "p7"
        for r in sorted(batch, key=lambda a: a[key], reverse=True):
            if len(selected) >= QUANT_MAX_PICKS:
                break
            if r["symbol"] in selected:
                continue
            sec = r.get("sector", "Unknown")
            if sec != "Unknown" and sec in selected_sectors:
                continue
            if not baseline and (r["p7"] < threshold or r["expected_net_pct"] <= 0):
                continue
            if baseline and r["baseline_score"] < 60:
                continue
            selected.add(r["symbol"])
            selected_sectors.add(sec)
            picks.append(r)
    return picks


def metrics(rows):
    signal_count = len(rows)
    rows = [r for r in rows if r["outcome"].get("return_pct") is not None]
    if not rows:
        return {"signals": signal_count, "trades": 0, "mean_net_pct": 0.0, "p7_hit_rate": 0.0, "p10_hit_rate": 0.0,
                "lower_mean_bound": -100.0, "max_drawdown_pct": 0.0, "days": 0}
    ret = np.array([r["outcome"]["return_pct"] for r in rows])
    daily = {}
    for r in rows:
        daily.setdefault(r["date"], []).append(r["outcome"]["return_pct"])
    # Cluster uncertainty by session, not thousands of correlated intraday rows.
    means = np.array([np.mean(v) for _, v in sorted(daily.items())])
    lower = float(means.mean() - 1.96 * means.std(ddof=1) / np.sqrt(len(means))) if len(means) > 1 else -100.0
    # Equal one-third notional per slot, cash in unused slots; no leverage.
    daily_ret = np.array([sum(v)/3 for _, v in sorted(daily.items())])
    equity = np.r_[1.0, np.cumprod(1 + daily_ret/100)]
    drawdown = equity / np.maximum.accumulate(equity) - 1
    return {"signals": signal_count, "trades": len(rows), "days": len(daily), "mean_net_pct": round(float(ret.mean()), 4),
            "p7_hit_rate": round(float(np.mean([r["outcome"]["hit7"] for r in rows])), 4),
            "p10_hit_rate": round(float(np.mean([r["outcome"]["hit10"] for r in rows])), 4),
            "lower_mean_bound": round(lower, 4), "max_drawdown_pct": round(float(-drawdown.min()*100), 4)}


def training_rows(store):
    with store.connect() as c:
        rows = c.execute("SELECT o.features,t.value,o.provenance FROM observations o JOIN outcomes t ON t.observation_id=o.id WHERE t.resolved=1 AND o.reason='eligible' ORDER BY o.ts,o.symbol").fetchall()
    out = []
    for row in rows:
        f, outcome = json.loads(row[0]), json.loads(row[1])
        if (f.get("feature_version") == VERSION and gate(f) == "eligible"
                and (outcome.get("return_pct") is not None or outcome.get("status") == "unfilled")):
            out.append({**f, "outcome": outcome, "recording_provenance": row[2]})
    return out


def active_model(store, date):
    from config import QUANT_MODEL_MAX_AGE_DAYS, QUANT_COST_BPS, QUANT_SLIPPAGE_BPS
    with store.connect() as c:
        rows = c.execute("SELECT value FROM models WHERE promoted=1 ORDER BY created_at DESC").fetchall()
    for r in rows:
        m = json.loads(r[0])
        if m.get("feature_version") != VERSION or m["evaluated_through"] >= date:
            continue
        if m.get("cost_bps") != QUANT_COST_BPS or m.get("slippage_bps") != QUANT_SLIPPAGE_BPS:
            continue
        age = (dt.date.fromisoformat(date) - dt.date.fromisoformat(m["evaluated_through"])).days
        if age <= QUANT_MODEL_MAX_AGE_DAYS:
            return m
    return None


def shadow_model(store, date):
    """Latest non-promoted model for visible shadow probabilities only."""
    from config import QUANT_MODEL_MAX_AGE_DAYS, QUANT_COST_BPS, QUANT_SLIPPAGE_BPS
    with store.connect() as c:
        rows = c.execute("SELECT value FROM models WHERE promoted=0 ORDER BY created_at DESC").fetchall()
    for row in rows:
        model = json.loads(row[0])
        if model.get("feature_version") != VERSION or model.get("evaluated_through", date) >= date:
            continue
        if model.get("cost_bps") != QUANT_COST_BPS or model.get("slippage_bps") != QUANT_SLIPPAGE_BPS:
            continue
        if (dt.date.fromisoformat(date) - dt.date.fromisoformat(model["evaluated_through"])).days <= QUANT_MODEL_MAX_AGE_DAYS:
            return model
    return None


def evidence_progress(rows):
    historical = [row for row in rows if row.get("recording_provenance") != "live"]
    forward = [row for row in rows if row.get("recording_provenance") == "live"]
    return {
        "historical_sessions": len({row["date"] for row in historical}),
        "historical_samples": len(historical),
        "forward_sessions": len({row["date"] for row in forward}),
        "forward_eligible_observations": len(forward),
        "target7_positive_examples": sum(int(row["outcome"].get("hit7") or 0) for row in rows),
        "target10_positive_examples": sum(int(row["outcome"].get("hit10") or 0) for row in rows),
    }


def train(store):
    from config import (QUANT_MIN_MODEL_DAYS, QUANT_MIN_MODEL_SAMPLES, QUANT_MIN_EVAL_TRADES,
                        QUANT_FORWARD_MIN_DAYS, QUANT_COST_BPS, QUANT_SLIPPAGE_BPS)
    rows = training_rows(store)
    days = sorted({r["date"] for r in rows})
    progress = evidence_progress(rows)
    if len(days) < QUANT_MIN_MODEL_DAYS or len(rows) < QUANT_MIN_MODEL_SAMPLES:
        result = {"status": "backfilling", "sessions": len(days), "samples": len(rows),
                  "required_sessions": QUANT_MIN_MODEL_DAYS, "required_samples": QUANT_MIN_MODEL_SAMPLES,
                  "remaining_sessions": max(0, QUANT_MIN_MODEL_DAYS-len(days)),
                  "remaining_samples": max(0, QUANT_MIN_MODEL_SAMPLES-len(rows)), **progress}
        store.put("learning", result)
        return result
    a, b = max(1, int(len(days)*0.5)), int(len(days)*0.7)
    train_rows = [r for r in rows if r["date"] < days[a] and r["outcome"].get("return_pct") is not None]
    cal_rows = [r for r in rows if days[a] <= r["date"] < days[b] and r["outcome"].get("return_pct") is not None]
    test_rows = [r for r in rows if r["date"] >= days[b]]
    if not train_rows or not cal_rows:
        result = {"status": "insufficient_filled_samples", "sessions": len(days), "samples": len(rows)}
        store.put("learning", result)
        return result
    x = np.array([[r[k] for k in FEATURES] for r in train_rows])
    mean, scale = x.mean(axis=0), np.maximum(x.std(axis=0), 1e-3)
    x = np.clip((x-mean)/scale, -8, 8)
    xc = np.clip((np.array([[r[k] for k in FEATURES] for r in cal_rows])-mean)/scale, -8, 8)
    model = {"feature_version": VERSION, "mean": mean.tolist(), "scale": scale.tolist(),
             "weights": {}, "calibration": {}, "trained_through": days[a-1],
             "calibrated_through": days[b-1], "evaluated_through": days[-1],
             "cost_bps": QUANT_COST_BPS, "slippage_bps": QUANT_SLIPPAGE_BPS,
             "exit_policy": "half_7_half_10_runner_stop_3.5", "coverage": "available_historical_universe"}
    for target in ("7", "10"):
        y = np.array([r["outcome"]["hit"+target] for r in train_rows], dtype=float)
        yc = np.array([r["outcome"]["hit"+target] for r in cal_rows], dtype=float)
        if min(y.sum(), len(y)-y.sum()) < 10 or min(yc.sum(), len(yc)-yc.sum()) < 5:
            result = {"status": "insufficient_target_examples", "target": target,
                      "train_positives": int(y.sum()), "calibration_positives": int(yc.sum())}
            store.put("learning", result)
            return result
        w = _fit(x, y)
        logits = w[0] + xc @ w[1:]
        calibration = _fit(logits[:, None], yc)
        model["weights"][target], model["calibration"][target] = w.tolist(), calibration.tolist()
    xr = np.column_stack([np.ones(len(x)), x])
    model["return_weights"] = np.linalg.solve(xr.T @ xr + np.eye(xr.shape[1])*5,
                                              xr.T @ np.array([r["outcome"]["return_pct"] for r in train_rows])).tolist()
    model["id"] = hashlib.sha256(dumps(model).encode()).hexdigest()[:16]
    proposed = predict(model, test_rows)
    score, baseline = metrics(portfolio(proposed)), metrics(portfolio(test_rows, baseline=True))
    filled_proposed = [r for r in proposed if r["outcome"].get("return_pct") is not None]
    p = np.array([r["p7"] for r in filled_proposed]); y = np.array([r["outcome"]["hit7"] for r in filled_proposed])
    brier = float(np.mean((p-y)**2)) if len(y) else 1.0
    base_rate = float(np.mean([r["outcome"]["hit7"] for r in train_rows]))
    null_brier = float(np.mean((base_rate-y)**2)) if len(y) else 0.0
    prior = active_model(store, days[b])
    prior_score = metrics(portfolio(predict(prior, test_rows))) if prior else None
    # Never re-use evaluation sessions to claim a fresh improvement on a later
    # promotion; freeze the previous model and require a new evaluation window.
    latest_eval = store.get("last_promotion_evaluation", "")
    fresh = days[b] > latest_eval
    live_picks = portfolio([r for r in proposed if r.get("recording_provenance") == "live"])
    forward = metrics(live_picks)
    forward_baseline = metrics(portfolio([r for r in test_rows if r.get("recording_provenance") == "live"], baseline=True))
    forward_ready = (forward["trades"] >= QUANT_MIN_EVAL_TRADES and forward["days"] >= QUANT_FORWARD_MIN_DAYS
                     and forward["lower_mean_bound"] > 0
                     and forward["mean_net_pct"] > forward_baseline["mean_net_pct"])
    promote = (fresh and forward_ready and score["trades"] >= QUANT_MIN_EVAL_TRADES and score["days"] >= 5
               and score["lower_mean_bound"] > 0 and brier <= null_brier
               and score["mean_net_pct"] > baseline["mean_net_pct"]
               and (prior_score is None or score["mean_net_pct"] > prior_score["mean_net_pct"]))
    result = {"status": "promoted" if promote else ("candidate_rejected" if forward_ready else "insufficient_forward_evidence"), "model_id": model["id"],
              "sessions": len(days), "samples": len(rows), "evaluation_start": days[b],
              "evaluation_end": days[-1], "model": score, "baseline": baseline,
              "previous_model": prior_score, "brier": brier, "base_rate_brier": null_brier,
              "forward_recorded": forward, "forward_baseline": forward_baseline, "forward_evidence_ready": forward_ready,
              "required_forward_sessions": QUANT_FORWARD_MIN_DAYS, "required_forward_observations": QUANT_MIN_EVAL_TRADES,
              "remaining_forward_sessions": max(0, QUANT_FORWARD_MIN_DAYS-forward["days"]),
              "remaining_forward_observations": max(0, QUANT_MIN_EVAL_TRADES-forward["trades"]),
              "fresh_evaluation": fresh, "note": "Historical modeled fills; forward evidence still required.", **progress}
    model["evaluation"] = result
    with store.connect() as c:
        c.execute("INSERT OR IGNORE INTO models VALUES (?,?,?,?)", (model["id"], int(time.time()), dumps(model), int(promote)))
    if promote:
        store.put("last_promotion_evaluation", days[-1])
    store.put("learning", result)
    return result
