"""
modules/experiment_registry.py — Experiment Registry, Shadow Models & Promotion Pipeline.

Governs all research experiments and model candidates.
Guarantees:
- Auditable walk-forward evidence pipeline.
- Strict promotion gates (min 20 forward sessions, min 30 trades, positive 95% lower confidence bound).
- ZERO unvalidated models or experimental parameters can reach production live alerts.
"""
from __future__ import annotations

import json
import logging
import sqlite3
import time
from typing import Any, Dict, List, Optional, Tuple

from modules.quant_store import Store, dumps

LOG = logging.getLogger(__name__)


def ensure_experiment_tables(store: Optional[Store] = None) -> None:
    """Ensure research_experiments schema exists in quant.db."""
    store = store or Store()
    with store.connect() as c:
        c.execute("""
            CREATE TABLE IF NOT EXISTS research_experiments (
                experiment_id TEXT PRIMARY KEY,
                version_tag TEXT NOT NULL,
                base_model_id TEXT NOT NULL,
                hypothesis TEXT NOT NULL,
                features_spec TEXT NOT NULL,
                cost_model_version TEXT NOT NULL,
                slippage_model_version TEXT NOT NULL,
                status TEXT NOT NULL,
                backtest_metrics TEXT,
                forward_metrics TEXT,
                promotion_reason TEXT,
                created_at INTEGER NOT NULL,
                updated_at INTEGER NOT NULL
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_exp_status ON research_experiments(status);")


def register_experiment(
    experiment_id: str,
    version_tag: str,
    base_model_id: str,
    hypothesis: str,
    features_spec: Any,
    cost_model_version: str = "cost_v2_statutory_nse",
    slippage_model_version: str = "slip_v2_dynamic",
    store: Optional[Store] = None,
) -> Dict[str, Any]:
    """Register a new research experiment in 'proposed' state."""
    store = store or Store()
    ensure_experiment_tables(store)

    now = int(time.time())
    spec_json = dumps(features_spec) if not isinstance(features_spec, str) else features_spec

    with store.connect() as c:
        c.execute("""
            INSERT OR REPLACE INTO research_experiments
            (experiment_id, version_tag, base_model_id, hypothesis, features_spec,
             cost_model_version, slippage_model_version, status, backtest_metrics,
             forward_metrics, promotion_reason, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, 'proposed', NULL, NULL, NULL, ?, ?)
        """, (experiment_id, version_tag, base_model_id, hypothesis, spec_json,
              cost_model_version, slippage_model_version, now, now))

    return {
        "experiment_id": experiment_id,
        "version_tag": version_tag,
        "status": "proposed",
        "created_at": now,
    }


def update_experiment_status(
    experiment_id: str,
    status: str,
    backtest_metrics: Optional[Dict[str, Any]] = None,
    forward_metrics: Optional[Dict[str, Any]] = None,
    reason: str = "",
    store: Optional[Store] = None,
) -> bool:
    """Update status, metrics or failure reasons for an experiment."""
    valid_statuses = {"proposed", "backtesting", "shadow", "forward_testing", "rejected", "promoted"}
    if status not in valid_statuses:
        raise ValueError(f"Invalid experiment status '{status}'. Must be one of {valid_statuses}")

    store = store or Store()
    ensure_experiment_tables(store)

    now = int(time.time())
    with store.connect() as c:
        row = c.execute("SELECT experiment_id FROM research_experiments WHERE experiment_id=?", (experiment_id,)).fetchone()
        if not row:
            return False

        updates = ["status = ?", "updated_at = ?"]
        params = [status, now]

        if backtest_metrics is not None:
            updates.append("backtest_metrics = ?")
            params.append(dumps(backtest_metrics))

        if forward_metrics is not None:
            updates.append("forward_metrics = ?")
            params.append(dumps(forward_metrics))

        if reason:
            updates.append("promotion_reason = ?")
            params.append(reason)

        params.append(experiment_id)
        c.execute(f"UPDATE research_experiments SET {', '.join(updates)} WHERE experiment_id = ?", params)

    return True


def get_experiment(experiment_id: str, store: Optional[Store] = None) -> Optional[Dict[str, Any]]:
    """Retrieve full record of a single experiment."""
    store = store or Store()
    ensure_experiment_tables(store)
    with store.connect() as c:
        row = c.execute("SELECT * FROM research_experiments WHERE experiment_id=?", (experiment_id,)).fetchone()
    if not row:
        return None

    d = dict(row)
    if d.get("backtest_metrics"):
        try:
            d["backtest_metrics"] = json.loads(d["backtest_metrics"])
        except Exception:
            pass
    if d.get("forward_metrics"):
        try:
            d["forward_metrics"] = json.loads(d["forward_metrics"])
        except Exception:
            pass
    return d


def list_experiments(status: Optional[str] = None, store: Optional[Store] = None) -> List[Dict[str, Any]]:
    """List experiments, optionally filtered by status."""
    store = store or Store()
    ensure_experiment_tables(store)
    with store.connect() as c:
        if status:
            rows = c.execute("SELECT * FROM research_experiments WHERE status=? ORDER BY created_at DESC", (status,)).fetchall()
        else:
            rows = c.execute("SELECT * FROM research_experiments ORDER BY created_at DESC").fetchall()

    results = []
    for r in rows:
        d = dict(r)
        if d.get("backtest_metrics"):
            try:
                d["backtest_metrics"] = json.loads(d["backtest_metrics"])
            except Exception:
                pass
        if d.get("forward_metrics"):
            try:
                d["forward_metrics"] = json.loads(d["forward_metrics"])
            except Exception:
                pass
        results.append(d)
    return results


def can_promote_experiment(
    experiment_id: str,
    min_forward_sessions: int = 20,
    min_trades: int = 30,
    min_net_return: float = 0.5,
    store: Optional[Store] = None,
) -> Tuple[bool, str]:
    """
    Strict mathematical gate for model promotion.
    Returns (True, "Promotion criteria satisfied") or (False, "Failure explanation").
    """
    exp = get_experiment(experiment_id, store=store)
    if not exp:
        return False, f"Experiment {experiment_id} not found."

    if exp["status"] not in ("forward_testing", "shadow"):
        return False, f"Experiment is in '{exp['status']}' state; must be 'forward_testing' or 'shadow'."

    fwd = exp.get("forward_metrics")
    if not fwd or not isinstance(fwd, dict):
        return False, "Missing forward paper trading metrics."

    sessions = fwd.get("days") or fwd.get("sessions") or 0
    trades = fwd.get("trades") or 0
    lower_bound = fwd.get("lower_mean_bound", -100.0)
    mean_net = fwd.get("mean_net_pct", -100.0)

    if sessions < min_forward_sessions:
        return False, f"Insufficient forward sessions ({sessions} < {min_forward_sessions} required)."

    if trades < min_trades:
        return False, f"Insufficient executed forward trades ({trades} < {min_trades} required)."

    if lower_bound <= 0:
        return False, f"Statistical confidence bound not positive (lower_bound={lower_bound:.3f}% <= 0%)."

    if mean_net < min_net_return:
        return False, f"Mean net return ({mean_net:.3f}%) below hurdle rate ({min_net_return}%)."

    return True, "Promotion criteria satisfied."


def promote_experiment(
    experiment_id: str,
    reason: str,
    store: Optional[Store] = None,
) -> Tuple[bool, str]:
    """
    Attempt to promote an experiment to production model status.
    Enforces strict validation gate before applying promotion.
    """
    store = store or Store()
    can_promote, msg = can_promote_experiment(experiment_id, store=store)
    if not can_promote:
        update_experiment_status(experiment_id, "rejected", reason=f"Promotion failed: {msg}", store=store)
        return False, msg

    exp = get_experiment(experiment_id, store=store)
    update_experiment_status(experiment_id, "promoted", reason=reason, store=store)

    # If associated model exists in models table, mark promoted = 1
    base_id = exp.get("base_model_id")
    if base_id:
        with store.connect() as c:
            c.execute("UPDATE models SET promoted=1 WHERE id=?", (base_id,))

    return True, f"Successfully promoted {experiment_id}: {reason}"
