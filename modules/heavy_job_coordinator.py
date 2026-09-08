"""Coordinate expensive background jobs and rotating scan progress.

This module keeps core agents enabled while preventing them from competing for
network/CPU at the same time. It is intentionally fail-open for callers: if the
state file cannot be read, the job is allowed rather than blocking the system.
"""

from __future__ import annotations

import contextlib
import datetime as dt
import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any, Iterator

from modules.time_utils import now_ist, today_ist_str

logger = logging.getLogger(__name__)

STATE_FILE = os.path.join("data", "heavy_job_state.json")
PROGRESS_FILE = os.path.join("data", "agent_scan_progress.json")
_state_lock = threading.RLock()


def _enabled() -> bool:
    try:
        from config import HEAVY_JOB_LOCK_ENABLED

        return bool(HEAVY_JOB_LOCK_ENABLED)
    except Exception:
        return True


def _max_jobs() -> int:
    try:
        from config import MAX_HEAVY_JOBS_AT_ONCE

        return max(1, int(MAX_HEAVY_JOBS_AT_ONCE))
    except Exception:
        return 1


def _now_epoch() -> float:
    return time.time()


def _load_json(path: str, default: dict[str, Any]) -> dict[str, Any]:
    try:
        if os.path.exists(path):
            with open(path, "r", encoding="utf-8") as fp:
                data = json.load(fp)
            return data if isinstance(data, dict) else default
    except Exception as exc:
        logger.debug("Could not load %s: %s", path, exc)
    return default


def _save_json(path: str, payload: dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = f"{path}.tmp"
    with open(tmp, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=False, default=str)
    os.replace(tmp, path)


def _active_jobs(state: dict[str, Any], stale_after_seconds: int) -> list[dict[str, Any]]:
    now = _now_epoch()
    active = []
    for job in state.get("active_jobs", []) or []:
        try:
            started = float(job.get("started_epoch") or 0)
        except Exception:
            started = 0
        if started and now - started <= stale_after_seconds:
            active.append(job)
    return active


@dataclass
class HeavyJobLease:
    job_name: str
    owner: str
    acquired: bool
    reason: str = ""


@contextlib.contextmanager
def acquire_heavy_job(
    job_name: str,
    *,
    priority: int = 3,
    stale_after_seconds: int = 1800,
    wait: bool = False,
    wait_timeout_seconds: int = 0,
) -> Iterator[HeavyJobLease]:
    """Acquire a lightweight cross-agent heavy-job lease.

    The default is non-blocking. Live agents should skip and retry later when a
    heavy job is already active.
    """

    if not _enabled():
        yield HeavyJobLease(job_name=job_name, owner="disabled", acquired=True, reason="lock_disabled")
        return

    owner = f"{os.getpid()}-{threading.get_ident()}-{uuid.uuid4().hex[:8]}"
    deadline = _now_epoch() + max(0, wait_timeout_seconds)
    lease = HeavyJobLease(job_name=job_name, owner=owner, acquired=False, reason="busy")

    while True:
        with _state_lock:
            state = _load_json(STATE_FILE, {"active_jobs": [], "history": []})
            active = _active_jobs(state, stale_after_seconds)
            if len(active) < _max_jobs():
                record = {
                    "job_name": job_name,
                    "owner": owner,
                    "priority": priority,
                    "started_at": now_ist().isoformat(timespec="seconds"),
                    "started_epoch": _now_epoch(),
                }
                active.append(record)
                state["active_jobs"] = active
                state["current_job"] = record
                _save_json(STATE_FILE, state)
                lease = HeavyJobLease(job_name=job_name, owner=owner, acquired=True, reason="acquired")
                break
            lease = HeavyJobLease(
                job_name=job_name,
                owner=owner,
                acquired=False,
                reason=f"busy:{active[0].get('job_name', 'unknown') if active else 'unknown'}",
            )

        if not wait or _now_epoch() >= deadline:
            yield lease
            return
        time.sleep(2)

    try:
        yield lease
    finally:
        release_heavy_job(lease)


def release_heavy_job(lease: HeavyJobLease) -> None:
    if not lease.acquired or not _enabled():
        return
    with _state_lock:
        state = _load_json(STATE_FILE, {"active_jobs": [], "history": []})
        active = []
        released = None
        for job in state.get("active_jobs", []) or []:
            if job.get("owner") == lease.owner:
                released = job
            else:
                active.append(job)
        if released:
            released["finished_at"] = now_ist().isoformat(timespec="seconds")
            state["history"] = (state.get("history", []) + [released])[-50:]
        state["active_jobs"] = active
        state["current_job"] = active[0] if active else None
        _save_json(STATE_FILE, state)


def get_heavy_job_state() -> dict[str, Any]:
    with _state_lock:
        state = _load_json(STATE_FILE, {"active_jobs": [], "history": []})
        state["active_jobs"] = _active_jobs(state, 1800)
        state["lock_enabled"] = _enabled()
        state["max_jobs"] = _max_jobs()
        return state


def rotating_batch(agent_name: str, symbols: list[str], batch_size: int) -> tuple[list[str], dict[str, Any]]:
    """Return the next daily rotating batch and persist progress."""

    clean = [str(s).strip().upper() for s in symbols if str(s).strip()]
    total = len(clean)
    if total <= 0:
        return [], {"agent": agent_name, "date": today_ist_str(), "total": 0, "progress_pct": 0.0}

    batch_size = max(1, int(batch_size or total))
    today = today_ist_str()

    with _state_lock:
        state = _load_json(PROGRESS_FILE, {})
        agent = state.get(agent_name, {})
        if agent.get("date") != today:
            agent = {"date": today, "next_index": 0, "completed_symbols": []}

        start = int(agent.get("next_index") or 0)
        if start >= total:
            start = 0
            agent["completed_symbols"] = []

        end = min(total, start + batch_size)
        batch = clean[start:end]
        completed = set(agent.get("completed_symbols") or [])
        completed.update(batch)
        next_index = 0 if end >= total else end

        progress = {
            "agent": agent_name,
            "date": today,
            "start_index": start,
            "end_index": end,
            "next_index": next_index,
            "batch_size": len(batch),
            "total": total,
            "completed_today": len(completed) if next_index else total,
            "progress_pct": round((len(completed) if next_index else total) * 100.0 / total, 2),
            "updated_at": now_ist().isoformat(timespec="seconds"),
        }
        state[agent_name] = {**progress, "completed_symbols": sorted(completed) if next_index else []}
        _save_json(PROGRESS_FILE, state)
        return batch, progress


def get_scan_progress() -> dict[str, Any]:
    with _state_lock:
        state = _load_json(PROGRESS_FILE, {})
        state["_date"] = today_ist_str()
        return state
