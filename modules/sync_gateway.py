"""
modules/sync_gateway.py — Real-Time Zero-Delay System & Dashboard Sync Gateway.

Features:
- Thread-safe Pub/Sub event bus linking backend engines and SSE dashboard clients.
- Sub-5ms in-memory consolidated state cache.
- Event broadcasting for ticks, runner milestone shifts, circuit breakers, and archives.
- Multi-client SSE queue management with instantaneous event delivery and keepalive heartbeats.
"""

from __future__ import annotations

import datetime
import json
import logging
import queue
import threading
import time
import uuid
from typing import Any, Dict, Iterator, List, Optional

logger = logging.getLogger(__name__)


def _now_str() -> str:
    try:
        from modules.time_utils import now_ist
        return now_ist().strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def _now_iso() -> str:
    try:
        from modules.time_utils import now_ist
        return now_ist().isoformat(timespec="seconds")
    except Exception:
        return datetime.datetime.now().isoformat(timespec="seconds")


class SyncGateway:
    """Central event broker and state aggregator for zero-delay dashboard synchronization."""

    def __init__(self, max_history: int = 100):
        self._lock = threading.Lock()
        self._clients: Dict[str, queue.Queue] = {}
        self._max_history = max_history
        self._recent_events: List[Dict[str, Any]] = []

        # High-speed in-memory state cache
        self._state_cache: Dict[str, Any] = {
            "last_updated": _now_str(),
            "tracking": {},
            "risk_radar": {},
            "market_regime": {},
            "premarket": {},
            "archive": {
                "last_archive_time": None,
                "last_archive_dir": None,
                "total_archives": 0,
            },
        }

    # ─────────────────────────────────────────────────────────────────────────
    # Pub / Sub Subscription Management
    # ─────────────────────────────────────────────────────────────────────────

    def subscribe(self, client_id: Optional[str] = None) -> tuple[str, queue.Queue]:
        """Register a new SSE client connection and return its dedicated queue."""
        cid = client_id or str(uuid.uuid4())[:8]
        q: queue.Queue = queue.Queue(maxsize=100)
        with self._lock:
            self._clients[cid] = q
        logger.debug("SyncGateway client subscribed: %s (Total: %d)", cid, len(self._clients))
        return cid, q

    def unsubscribe(self, client_id: str) -> None:
        """Remove a disconnected SSE client queue."""
        with self._lock:
            if client_id in self._clients:
                del self._clients[client_id]
        logger.debug("SyncGateway client unsubscribed: %s (Remaining: %d)", client_id, len(self._clients))

    def publish(self, event_type: str, data: Any) -> None:
        """Broadcast an event immediately to all subscribed SSE clients."""
        payload = {
            "event": event_type,
            "timestamp": _now_str(),
            "data": data,
        }

        with self._lock:
            # Append to ring buffer
            self._recent_events.append(payload)
            if len(self._recent_events) > self._max_history:
                self._recent_events.pop(0)

            # Update cache where appropriate
            if event_type in ("TICK", "RUNNER_UPDATE") and isinstance(data, dict):
                self._state_cache["tracking"] = data
            elif event_type == "RISK_RADAR" and isinstance(data, dict):
                self._state_cache["risk_radar"] = data
            elif event_type == "MARKET_REGIME" and isinstance(data, dict):
                self._state_cache["market_regime"] = data
            elif event_type == "ARCHIVE_SAVED" and isinstance(data, dict):
                self._state_cache["archive"].update(data)
            elif event_type == "PREMARKET_SCAN" and isinstance(data, dict):
                self._state_cache["premarket"] = data

            self._state_cache["last_updated"] = _now_str()
            clients_snapshot = list(self._clients.items())

        # Non-blocking dispatch to all client queues
        for cid, q in clients_snapshot:
            try:
                q.put_nowait(payload)
            except queue.Full:
                logger.warning("Client queue full for %s, dropping frame", cid)
            except Exception as e:
                logger.debug("Dispatch error to client %s: %s", cid, e)

    # ─────────────────────────────────────────────────────────────────────────
    # In-Memory Cache & Snapshot Access (< 5ms response)
    # ─────────────────────────────────────────────────────────────────────────

    def get_state(self) -> Dict[str, Any]:
        """Return the consolidated in-memory state snapshot."""
        with self._lock:
            # Make a fast shallow copy
            snapshot = dict(self._state_cache)
            snapshot["server_time"] = _now_str()
            snapshot["active_clients"] = len(self._clients)
            snapshot["recent_events"] = list(self._recent_events[-10:])
            return snapshot

    def refresh_state_from_disk(self) -> Dict[str, Any]:
        """Perform a synchronous read of all persisted state files to prime cache."""
        try:
            from modules.stock_tracker import get_tracking_status
            self._state_cache["tracking"] = get_tracking_status()
        except Exception as e:
            logger.debug("Failed refreshing tracking cache: %s", e)

        try:
            from modules.paper_portfolio import get_portfolio_risk_radar
            self._state_cache["risk_radar"] = get_portfolio_risk_radar()
        except Exception as e:
            logger.debug("Failed refreshing risk radar cache: %s", e)

        try:
            import os
            cockpit_file = "data/premarket_cockpit.json"
            if os.path.exists(cockpit_file):
                with open(cockpit_file, "r", encoding="utf-8") as f:
                    cockpit = json.load(f)
                    self._state_cache["premarket"] = cockpit.get("picks", [])
                    self._state_cache["market_regime"] = cockpit.get("broad_market_regime", {})
        except Exception as e:
            logger.debug("Failed refreshing premarket cache: %s", e)

        try:
            from modules.record_archiver import list_archived_sessions
            archives = list_archived_sessions()
            if archives:
                latest = archives[0]
                self._state_cache["archive"] = {
                    "last_archive_time": latest.get("timestamp"),
                    "last_archive_dir": latest.get("folder_path"),
                    "last_archive_date": latest.get("date"),
                    "total_archives": len(archives),
                }
        except Exception as e:
            logger.debug("Failed refreshing archive info: %s", e)

        self._state_cache["last_updated"] = _now_str()
        return self.get_state()

    # ─────────────────────────────────────────────────────────────────────────
    # Helper Broadcasting Methods
    # ─────────────────────────────────────────────────────────────────────────

    def broadcast_tick(self, tracking_dict: dict) -> None:
        """Broadcast live tick update to dashboard clients."""
        self.publish("TICK", tracking_dict)

    def broadcast_runner_milestone(
        self, symbol: str, stage: str, current_price: float, pnl_pct: float, action_note: str = ""
    ) -> None:
        """Broadcast runner milestone change (Breakeven locked, TP1 booked, TP2 full winner, SL hit)."""
        self.publish("RUNNER_UPDATE", {
            "symbol": symbol,
            "stage": stage,
            "current_price": round(current_price, 2),
            "pnl_pct": round(pnl_pct, 2),
            "action_note": action_note,
            "time": _now_str(),
        })

    def broadcast_circuit_breaker(self, status: str, realized_drawdown: float) -> None:
        """Broadcast circuit breaker trip or risk level change."""
        self.publish("CIRCUIT_BREAKER", {
            "status": status,
            "realized_drawdown": round(realized_drawdown, 2),
            "timestamp": _now_str(),
        })

    def broadcast_archive_saved(self, archive_info: dict) -> None:
        """Broadcast that a daily session has been archived to disk."""
        self.publish("ARCHIVE_SAVED", archive_info)

    # ─────────────────────────────────────────────────────────────────────────
    # Server-Sent Events (SSE) Stream Generator
    # ─────────────────────────────────────────────────────────────────────────

    def sse_stream(self, timeout_sec: int = 600) -> Iterator[str]:
        """
        Yields Server-Sent Events with immediate initial state snapshot,
        real-time zero-delay push upon events, and 8s keepalive pings.
        """
        cid, q = self.subscribe()
        start_time = time.time()

        try:
            # 1. Immediate initial state push upon connection
            initial_state = self.get_state()
            yield f"event: INIT\ndata: {json.dumps(initial_state, default=str)}\n\n"

            # 2. Event loop
            while time.time() - start_time < timeout_sec:
                try:
                    payload = q.get(timeout=8.0)
                    evt = payload.get("event", "MESSAGE")
                    data_str = json.dumps(payload.get("data", {}), default=str)
                    yield f"event: {evt}\ndata: {data_str}\n\n"
                except queue.Empty:
                    # Keepalive heartbeat comment
                    yield f": ping {int(time.time())}\n\n"
        except GeneratorExit:
            pass
        finally:
            self.unsubscribe(cid)


# Global Singleton Instance
sync_gateway = SyncGateway()
