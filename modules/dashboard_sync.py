"""Synchronize dashboard-side state after important bot events."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


def sync_after_morning_telegram(picks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Refresh dashboard/paper/live terminal state after final picks reach Telegram."""
    result: dict[str, Any] = {"ok": True}

    try:
        from modules.paper_portfolio import allocate_today

        result["paper"] = allocate_today()
    except Exception as exc:
        result["ok"] = False
        result["paper_error"] = str(exc)
        logger.warning("Dashboard sync paper allocation failed: %s", exc)

    try:
        from modules.terminal_updater import refresh_terminal_state

        state = refresh_terminal_state()
        result["terminal"] = {
            "updated_at": state.get("updated_at"),
            "today_pick_count": state.get("today_pick_count"),
        }
    except Exception as exc:
        result["ok"] = False
        result["terminal_error"] = str(exc)
        logger.warning("Dashboard sync terminal refresh failed: %s", exc)

    try:
        from modules.grok_dashboard_agent import refresh_dashboard_state

        state = refresh_dashboard_state(use_ai=False)
        result["dashboard"] = {
            "updated_at": state.get("updated_at"),
            "latest_picks_date": state.get("latest_picks_date"),
            "pick_count": len(state.get("next_session_picks") or []),
        }
    except Exception as exc:
        result["ok"] = False
        result["dashboard_error"] = str(exc)
        logger.warning("Dashboard sync Grok dashboard refresh failed: %s", exc)

    logger.info("Dashboard sync after Telegram: %s", result)
    return result
