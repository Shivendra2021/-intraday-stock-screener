# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
alerts.py — Send Telegram notifications via raw requests (no library dependency).
Respects DRY_RUN mode: logs instead of sending.
"""

import logging
import datetime
import json
import os
import requests

from modules.time_utils import now_ist, today_ist_str

logger = logging.getLogger(__name__)


def _safe_error_text(value: object) -> str:
    text = str(value)
    try:
        from config import TELEGRAM_BOT_TOKEN

        if TELEGRAM_BOT_TOKEN:
            text = text.replace(TELEGRAM_BOT_TOKEN, "[redacted-token]")
    except Exception:
        pass
    return text


def _audit_send(event_type: str, ok: bool, details: str = "") -> None:
    os.makedirs("data", exist_ok=True)
    record = {
        "timestamp": now_ist().isoformat(timespec="seconds"),
        "date": today_ist_str(),
        "event_type": event_type,
        "ok": bool(ok),
        "details": _safe_error_text(details)[:500],
    }
    try:
        with open("data/telegram_delivery.jsonl", "a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        logger.debug("Could not write Telegram audit: %s", exc)


def _send(text: str, review_with_grok: bool = True, event_type: str = "telegram_message") -> bool:
    """
    Core Telegram send. Returns True on success.
    In DRY_RUN mode, logs the message and returns True.
    Includes retry logic with exponential backoff for rate limiting.
    """
    import time
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DRY_RUN

    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would send Telegram:\n{text}")
        _audit_send(event_type, True, "dry_run")
        return True

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not configured — skipping alert")
        _audit_send(event_type, False, "missing credentials")
        return False

    if review_with_grok:
        try:
            from modules.grok_brain import review_telegram_alert
            text = review_telegram_alert(text)
        except Exception as e:
            logger.warning(f"Grok Brain review failed, sending original alert: {e}")

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id":    TELEGRAM_CHAT_ID,
        "text":       text,
        "parse_mode": "HTML",
    }
    max_retries = 3
    from modules.http_session import http_post
    for attempt in range(max_retries):
        try:
            r = http_post(url, json=payload, timeout=15)
            if r.status_code == 200:
                logger.info("Telegram message sent successfully")
                _audit_send(event_type, True, "sent")
                return True
            elif r.status_code == 400 and ("parse" in r.text.lower() or "entity" in r.text.lower()):
                # HTML entity error - sanitize by stripping HTML tags and retry as clean text
                logger.warning("Telegram HTML parse error (%s), retrying as clean text...", r.text[:80])
                import re
                clean_text = re.sub(r"<[^>]+>", "", text)
                plain_payload = {
                    "chat_id": TELEGRAM_CHAT_ID,
                    "text": clean_text,
                }
                r_plain = http_post(url, json=plain_payload, timeout=15)
                if r_plain.status_code == 200:
                    logger.info("Telegram message sent successfully with plain text fallback")
                    _audit_send(event_type, True, "sent_plain_fallback")
                    return True
                else:
                    logger.error("Telegram fallback error %s: %s", r_plain.status_code, r_plain.text[:200])
                    _audit_send(event_type, False, f"{r_plain.status_code}: {r_plain.text[:200]}")
                    return False
            elif r.status_code == 429 or r.status_code == 503:
                # Rate limited — wait and retry
                wait_time = 2 ** attempt  # exponential backoff: 1s, 2s, 4s
                logger.warning(f"Telegram rate limited, retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"Telegram error {r.status_code}: {r.text[:200]}")
                _audit_send(event_type, False, f"{r.status_code}: {r.text[:200]}")
                return False
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning("Telegram request failed, retrying in %ss: %s", wait_time, _safe_error_text(e))
                time.sleep(wait_time)
                continue
            logger.error("Telegram send failed after %s attempts: %s", max_retries, _safe_error_text(e))
            _audit_send(event_type, False, _safe_error_text(e))
            return False
    return False


def send_raw_alert(text: str, review_with_grok: bool = True, event_type: str = "telegram_message") -> bool:
    """Public wrapper for sending a raw Telegram alert."""
    return _send(text, review_with_grok=review_with_grok, event_type=event_type)


# ─────────────────────────────────────────────────────────────────────────────
# Message builders
# ─────────────────────────────────────────────────────────────────────────────



# ─────────────────────────────────────────────────────────────────────────────
# Message builders
# ─────────────────────────────────────────────────────────────────────────────

def send_picks(picks: list, sentiment: float = 0.0) -> bool:
    """Send morning institutional runner picks message."""
    date_str = now_ist().strftime("%d %b %Y")

    if sentiment >= 0.3:
        sentiment_label = "🟢 Bullish"
    elif sentiment >= -0.1:
        sentiment_label = "🟡 Neutral"
    else:
        sentiment_label = "🔴 Bearish"

    lines = [
        f"🏛️ <b>HELIOS INSTITUTIONAL PICKS — {date_str}</b>",
        f"<i>5-Pillar Microstructure Validation • Super-Runner Portfolio</i>\n",
        "━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    ]

    for p in picks:
        rank = p.get("rank", 1)
        sym = p.get("symbol", "UNKNOWN")
        score = p.get("composite_score", p.get("score", p.get("confidence", 0)))
        entry = p.get("entry_trigger") or p.get("entry_price") or p.get("price", 0)
        sl_pct = p.get("ai_sl_pct", 1.8)
        sl_price = p.get("sl_price") or round(entry * (1 - sl_pct / 100), 2)
        tp1_pct = p.get("ai_tp1_pct", 7.0)
        tp1_price = round(entry * (1 + tp1_pct / 100), 2)
        tp2_pct = p.get("ai_tp2_pct", 10.2)
        tp2_price = round(entry * (1 + tp2_pct / 100), 2)
        be_price = round(entry * 1.035, 2)

        air = p.get("air_ratio")
        vcp = p.get("vcp_score")
        deliv = p.get("delivery_score") or p.get("delivery_pct")
        cat = p.get("catalyst")

        card = [
            f"<b>{rank}. {sym}</b> (Score: <b>{score:.1f}/100</b>)",
        ]
        if air is not None or vcp is not None:
            air_str = f"{air:.2f}x" if air else "N/A"
            vcp_str = f"{vcp:.0f}/100" if vcp else "N/A"
            card.append(f"   • AIR Imbalance: <b>{air_str}</b> | VCP: <b>{vcp_str}</b>")
        if deliv is not None:
            card.append(f"   • Delivery Absorption: <b>{deliv:.1f}%</b>")
        if cat:
            card.append(f"   • Catalyst: <i>{cat[:90]}</i>")

        card.append(
            f"   📈 Entry: <b>₹{entry:.2f}</b> | 🛑 SL: <b>₹{sl_price:.2f} (-{sl_pct:.1f}%)</b>\n"
            f"   🔒 BE Trail: <b>₹{be_price:.2f} (+3.5%)</b>\n"
            f"   🎯 TP1 (50% Out): <b>₹{tp1_price:.2f} (+{tp1_pct:.1f}%)</b>\n"
            f"   🚀 TP2 Runner:    <b>₹{tp2_price:.2f} (+{tp2_pct:.1f}%)</b>\n"
        )
        lines.append("\n".join(card))

    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append(f"Market Sentiment: {sentiment_label}")
    lines.append("⚠️ <i>Institutional Research Only. Not a trade recommendation.</i>")

    return _send("\n".join(lines), review_with_grok=False, event_type="morning_picks")


def send_tp_hit(symbol: str, ret: float) -> bool:
    """Send target-hit notification."""
    text = (
        f"✅ <b>TARGET HIT</b>\n"
        f"<b>{symbol}</b> reached target\n"
        f"Return: <b>+{ret:.2f}%</b>"
    )
    return _send(text)


def send_breakeven_hit(symbol: str, ret: float, entry_price: float = 0.0) -> bool:
    """Send Breakeven Hit notification (+3.5% achieved: SL moved to entry)."""
    entry_line = f"• New SL: <b>₹{entry_price:.2f} (Entry Price)</b>\n" if entry_price > 0 else ""
    text = (
        f"🔒 <b>BREAKEVEN SECURED: RISK-FREE TRADE</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"⚡ Stock: <b>{symbol}</b>\n"
        f"📈 Progress: <b>+{ret:.2f}% achieved (+3.5% Trigger)</b>\n"
        f"🛡️ Action Taken:\n"
        f"  • Stop Loss trailed to Entry\n"
        f"  {entry_line}"
        f"  • Downside risk is now eliminated (0% loss possible)\n"
        f"  • Riding momentum toward TP1 (+7.0%)\n\n"
        f"🎯 <i>House Money Mode: Position is 100% protected.</i>"
    )
    return _send(text, review_with_grok=False, event_type="breakeven_hit")


def send_tp1_hit(symbol: str, ret: float, new_sl: float = 0.0) -> bool:
    """Send Target 1 hit notification (50% profit booked, trailing remaining 50% to +3.5%)."""
    sl_line = f"• Trailing SL on Runner: <b>₹{new_sl:.2f} (+3.50% profit locked)</b>\n" if new_sl > 0 else ""
    text = (
        f"🎯 <b>TARGET 1 HIT: 50% PROFIT SECURED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"✅ Stock: <b>{symbol}</b>\n"
        f"📈 Gain: <b>+{ret:.2f}% achieved (TP1 +7.0% Target)</b>\n"
        f"💼 Institutional Execution:\n"
        f"  • 50% Quantity: <b>Closed & Cash Booked</b>\n"
        f"  • Remaining 50%: <b>Riding to TP2 Super-Runner (+10.2%)</b>\n"
        f"  {sl_line}\n"
        f"🚀 <i>Trade is permanently green. Letting the winner run!</i>"
    )
    return _send(text, review_with_grok=False, event_type="tp1_hit")


def send_tp2_hit(symbol: str, ret: float) -> bool:
    """Send Target 2 Super-Runner hit notification (100% target reached)."""
    text = (
        f"🚀🔥 <b>SUPER-RUNNER TARGET 2 ACHIEVED (+10.2%)</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🏆 Stock: <b>{symbol}</b>\n"
        f"💰 Final Gain: <b>+{ret:.2f}% achieved</b>\n"
        f"📊 Execution:\n"
        f"  • Full Runner Target Reached\n"
        f"  • Remaining Position Liquidated\n"
        f"  • Maximum Institutional Alpha Captured\n\n"
        f"👑 <i>Pillar-Validated Super-Runner Complete!</i>"
    )
    return _send(text, review_with_grok=False, event_type="tp2_hit")


def send_circuit_breaker_alert(sl_count: int, max_sl: int = 2, loss_pct: float = 0.0) -> bool:
    """Send Daily Circuit Breaker lockdown notification."""
    text = (
        f"🚨 <b>DAILY LOSS CIRCUIT BREAKER ENGAGED</b>\n"
        f"━━━━━━━━━━━━━━━━━━━━━\n"
        f"🛡️ <b>Protection:</b> Max daily stop-losses reached ({sl_count}/{max_sl})\n"
        f"📉 <b>Cumulative Loss:</b> {loss_pct:.2f}% (Within safe -2.0% cap)\n"
        f"⚡ <b>Action Taken:</b>\n"
        f"  • All pending trade scans paused for remainder of today.\n"
        f"  • No new afternoon momentum picks will be triggered.\n"
        f"  • Capital preserved to trade another day.\n\n"
        f"🔒 <i>Discipline Enforced: Preserving capital from choppy market conditions.</i>"
    )
    return _send(text, review_with_grok=False, event_type="circuit_breaker_alert")


def send_sl_hit(symbol: str, ret: float) -> bool:
    """Send stop-loss notification."""
    text = (
        f"🛑 <b>STOP LOSS HIT</b>\n"
        f"<b>{symbol}</b> hit stop loss\n"
        f"Return: <b>-{abs(ret):.2f}%</b>"
    )
    return _send(text)


def send_preclose(movers: list) -> bool:
    """Send pre-close momentum movers (3 PM scan)."""
    date_str = now_ist().strftime("%d %b %Y")
    lines = [f"📈 <b>Pre-Close Movers {date_str}</b>", "Stocks up 4–7% with volume spike\n"]
    for i, m in enumerate(movers[:10], start=1):
        lines.append(
            f"{i}. <b>{m['symbol']}</b> | "
            f"+{m['move_pct']:.1f}% | "
            f"Vol: {m['vol_ratio']:.1f}x avg"
        )
    lines.append("\n⚠️ <i>Research only. Not a trade recommendation.</i>")
    return _send("\n".join(lines))


def send_preclose_alert(movers: list) -> bool:
    """Alias for preclose alert - uses same format."""
    return send_preclose(movers)


def send_summary(stats: dict) -> bool:
    """Send end-of-day daily summary."""
    date_str = now_ist().strftime("%d %b %Y")
    acc = stats.get("accuracy", 0)
    avg_ret = stats.get("avg_return", 0)
    ret_sign = "+" if avg_ret >= 0 else ""

    text = (
        f"📋 <b>Daily Summary {date_str}</b>\n"
        f"✅ TP Hit: {stats.get('tp_count', 0)}\n"
        f"🛑 SL Hit: {stats.get('sl_count', 0)}\n"
        f"📊 Accuracy: {acc:.1f}%\n"
        f"💰 Avg Return: {ret_sign}{avg_ret:.2f}%"
    )
    return _send(text)


def send_no_picks(reason: str = "No stocks passed filters", diagnostics: dict | None = None) -> bool:
    """Send notification when no picks generated today."""
    date_str = now_ist().strftime("%d %b %Y")
    diagnostic_lines = ""
    if diagnostics:
        checked = diagnostics.get("symbols") or diagnostics.get("universe_size") or 0
        candidates = diagnostics.get("candidates_found", 0)
        no_data = diagnostics.get("no_data", 0)
        low_price = diagnostics.get("price_below_filter", 0)
        low_volume = diagnostics.get("volume_below_filter", 0)
        errors = diagnostics.get("error", 0) + diagnostics.get("batch_failures", 0)
        diagnostic_lines = (
            "\n\n<b>Diagnostics</b>\n"
            f"Checked: {checked} symbols\n"
            f"Candidates: {candidates}\n"
            f"No data: {no_data} | Low price: {low_price} | Low volume: {low_volume} | Errors: {errors}"
        )
    text = (
        f"📊 <b>MarketMind Pro - {date_str}</b>\n"
        f"\n⚠️ <b>No Picks Generated</b>\n"
        f"Reason: {reason}\n"
        f"{diagnostic_lines}\n"
        f"\n<i>Scanner returned zero qualifying candidates after fallback checks.</i>\n"
        f"<i>This can be caused by data-source gaps, strict filters, timing, or market conditions.</i>\n"
        f"<i>Bot is running - analysis complete.</i>"
    )
    return _send(text)


def send_heartbeat(universe_count: int, market_status: str, dry_run: bool, last_analysis: str = "N/A") -> bool:
    """Daily heartbeat - confirms bot is alive."""
    date_str = now_ist().strftime("%d %b %Y %H:%M")
    dry_status = "🔴 ACTIVE (ALERTS ENABLED)" if not dry_run else "🟡 DRY_RUN (TEST MODE)"
    text = (
        f"✅ <b>MarketMind Pro — Heartbeat</b>\n"
        f"Date: {date_str}\n"
        f"Mode: {dry_status}\n"
        f"Universe: {universe_count} stocks\n"
        f"Market: {market_status}\n"
        f"Last Analysis: {last_analysis}\n"
        f"Status: <b>HEALTHY ✅</b>"
    )
    return _send(text)


def send_health_warning(issue: str, details: str = "") -> bool:
    """Send health warning - something may be wrong."""
    text = (
        f"⚠️ <b>MarketMind Pro — HEALTH WARNING</b>\n"
        f"Issue: {issue}\n"
        f"Details: {details}\n"
        f"Action: Check bot logs immediately!"
    )
    return _send(text)


def send_intraday_alert(movers: list) -> bool:
    """Send intraday momentum alert (stocks up 3%+ with vol spike)."""
    if not movers:
        return True
    date_str = now_ist().strftime("%H:%M")
    lines = [f"⚡ <b>Intraday Movers @ {date_str}</b>"]
    for m in movers[:5]:
        lines.append(
            f"• <b>{m['symbol']}</b>: +{m['move_pct']:.1f}% | Vol: {m['vol_ratio']:.1f}x"
        )
    return _send("\n".join(lines))


def send_top_gainers(gainers: list) -> bool:
    """Send hourly top gainers alert."""
    if not gainers:
        return True
    date_str = now_ist().strftime("%H:%M")
    lines = [f"📈 <b>Top Gainers @ {date_str}</b>\n"]
    lines.append("Today's biggest movers:\n")
    for i, g in enumerate(gainers[:10], start=1):
        lines.append(
            f"{i}. <b>{g['symbol']}</b>: +{g['gain_pct']:.2f}% | ₹{g['price']:.2f}"
        )
    lines.append("\n⚠️ <i>Research only. Not a trade recommendation.</i>")
    return _send("\n".join(lines))


def send_end_of_day_report(performers: dict) -> bool:
    """Send end-of-day top 10 performers report after market close."""
    if not performers:
        return True

    gainers = performers.get("gainers", [])
    losers = performers.get("losers", [])

    date_str = now_ist().strftime("%d %b %Y")

    lines = [f"📊 <b>MARKET WRAP - {date_str}</b>\n"]
    lines.append("="*30 + "\n")

    # Top Gainers
    lines.append(f"\n🟢 <b>TOP 10 GAINERS</b>\n")
    if gainers:
        for i, g in enumerate(gainers[:10], start=1):
            lines.append(
                f"{i:>2}. <b>{g['symbol']}</b>: +{g['gain_pct']:>6.2f}% | ₹{g['price']:.2f}"
            )
    else:
        lines.append("  No gainers found")

    # Top Losers
    lines.append(f"\n🔴 <b>TOP 10 LOSERS</b>\n")
    if losers:
        for i, l in enumerate(losers[:10], start=1):
            lines.append(
                f"{i:>2}. <b>{l['symbol']}</b>: {l['gain_pct']:>6.2f}% | ₹{l['price']:.2f}"
            )
    else:
        lines.append("  No losers found")

    lines.append("\n" + "="*30)
    lines.append("\n⚠️ <i>Research only. Not a trade recommendation.</i>")

    return _send("\n".join(lines))


def send_test_message() -> bool:
    """Send a test connectivity message."""
    text = " MarketMind Pro test message  setup successful!"
    return _send(text)


def send_startup_alert() -> bool:
    """Send startup schedule alert."""
    lines = [
        " MarketMind Pro Started ",
        "="*35,
        "",
        "Today's Schedule:",
        "",
        "  09:00  - Daily picks",
        "  10:00  - Hourly gainers",
        "  11:00  - Hourly gainers",
        "  12:00  - Hourly gainers",
        "  13:00  - Hourly gainers",
        "  14:00  - Hourly gainers",
        "  15:00  - Preclose movers",
        "  15:35  - TOP 10 performers",
        "  18:00  - Heartbeat",
        "",
        "Market open: 09:15 IST",
        "="*35,
    ]
    return _send("\n".join(lines), review_with_grok=False)


def send_pattern_picks(picks: list) -> bool:
    """Send pattern-based picks for tomorrow."""
    if not picks:
        return True

    lines = [
        f" MarketMind Pro - Tomorrow's Picks ",
        "="*40,
        "",
        "Pattern: Daily Change + Volume Surge",
        "Sector: Multiple (IT, Finance, Auto, Pharma)",
        "",
        "Top Picks:",
        "",
    ]

    for p in picks:
        lines.append(
            f"{p['rank']}. <b>{p['symbol']}</b>: ₹{p['current_price']:.2f} | "
            f"Change: +{p['change_pct']:.2f}% | Vol: {p['volume_ratio']:.1f}x"
        )
        lines.append(f"   Rec: {p['recommendation']} | Score: {p['score']}/7")

    lines.append("")
    lines.append("="*40)
    lines.append("\n⚠️ <i>Research only. Not a trade recommendation.</i>")

    return _send("\n".join(lines))


def send_morning_health_check(health: dict) -> bool:
    """Send morning health check status."""
    lines = [
        " Morning Health Check ",
        "="*40,
        "",
        f"Status: {health.get('status', 'unknown').upper()}",
        "",
    ]

    checks = health.get("checks", {})
    for check_name, check_value in checks.items():
        lines.append(f"  {check_name}: {check_value}")

    issues = health.get("issues", [])
    if issues:
        lines.append("")
        lines.append("Issues:")
        for issue in issues:
            lines.append(f"  - {issue}")

    lines.append("")
    lines.append("="*40)
    return _send("\n".join(lines))


def send_morning_news(report: dict) -> bool:
    """Send morning news and sector analysis."""
    sector_trends = report.get("sector_trends", {})

    lines = [
        " Morning Market Analysis ",
        "="*40,
        "",
        "Sector Trends:",
        "",
    ]

    sorted_sectors = sorted(sector_trends.items(), key=lambda x: x[1].get("avg_change", 0), reverse=True)

    for sector, data in sorted_sectors[:6]:
        change = data.get("avg_change", 0)
        symbol = "+" if change > 0 else ""
        lines.append(f"  {sector:<10}: {symbol}{change:>6.2f}%")

    lines.append("")
    lines.append("="*40)
    return _send("\n".join(lines))


def send_morning_final_picks(
    picks: list,
    accuracy: dict = None,
    review_with_grok: bool = True,
    session_type: str = "morning_final",
    source_label: str = "official_morning_pipeline",
) -> bool:
    """Send final morning picks with FULL technical data (RSI, ADX, EMA, prices)."""
    if not picks:
        return True

    is_official = session_type == "morning_final"
    title = "FINAL MORNING PICKS" if is_official else "LATE INTRADAY MOMENTUM SCAN"
    note = (
        "Official morning pipeline output."
        if is_official
        else "Late recovery scan only. Not official morning picks and not counted in morning dashboard."
    )
    audit_type = "morning_final_picks" if is_official else "late_intraday_picks"

    lines = [
        "📊 <b>FINAL MORNING PICKS - " + now_ist().strftime("%d %b %Y") + "</b>",
        "=" * 50,
        "",
    ]

    lines[0] = "📊 <b>" + title + " - " + now_ist().strftime("%d %b %Y") + "</b>"

    if accuracy:
        acc   = accuracy.get("accuracy_pct", 0)
        total = accuracy.get("total_picks", 0)
        tp    = accuracy.get("tp_hits", 0)
        sl    = accuracy.get("sl_hits", 0)
        lines.append(f"🎯 Bot Accuracy (30d): {acc}% | Total: {total} | ✅TP: {tp} | 🛑SL: {sl}")
        lines.append("")

    lines.append(f"📅 Date: {today_ist_str()}")
    lines.append("")
    lines.append(f"Source: {source_label}")
    lines.append(note)
    lines.append("")

    for p in picks:
        symbol     = p.get("symbol", "")
        rank       = p.get("rank", 0)
        price      = float(p.get("entry_price") or p.get("current_price") or p.get("price") or 0)
        sl_price   = float(p.get("sl_price") or (price * 0.98))
        target     = float(p.get("target_price") or (price * 1.065))
        score      = float(p.get("score", 0) or 0)
        rsi        = p.get("rsi", None)
        adx        = p.get("adx", None)
        vol_ratio  = p.get("vol_ratio", p.get("volume_ratio", None))
        ema        = p.get("ema_alignment", p.get("trend", "N/A"))
        gap        = p.get("gap_up", p.get("gap_up_pct", 0))
        daily_chg  = p.get("daily_change", p.get("change_pct", 0))
        dist_52w   = p.get("dist_52w_high", None)
        patterns   = p.get("patterns", [])
        sector     = p.get("sector", "")
        rr         = p.get("risk_reward", "N/A")
        reasons    = str(p.get("signal_reasons") or p.get("recommendation") or "momentum")
        grade      = p.get("confidence_grade", "")
        regime     = p.get("market_regime", "")

        # Risk classification based on score
        if score >= 70:
            risk_tag = "🟢 LOW"
        elif score >= 55:
            risk_tag = "🟡 MEDIUM"
        else:
            risk_tag = "🔴 HIGH"

        upside_pct = (target - price) / price * 100 if price > 0 else 0
        sl_pct     = (price - sl_price) / price * 100 if price > 0 else 0

        rsi_str  = f"{rsi:.1f}"   if rsi  is not None else "—"
        adx_str  = f"{adx:.1f}"   if adx  is not None else "—"
        vol_str  = f"{vol_ratio:.2f}x" if vol_ratio is not None else "—"
        dist_str = f"{dist_52w:.1f}% from 52wH" if dist_52w is not None else ""
        pat_str  = ", ".join(patterns[:2]) if patterns else "momentum"

        meta = []
        if sector:
            meta.append(str(sector))
        if grade:
            meta.append(f"Grade {grade}")
        if regime:
            meta.append(str(regime))
        suffix = f" [{' | '.join(meta)}]" if meta else ""
        tp1_price = float(p.get("tp1_price") or (price * 1.038))
        tp1_pct   = float(p.get("tp1_pct") or 3.8)
        tp2_price = target
        tp2_pct   = upside_pct
        lines.append(f"{rank}. <b>{symbol}</b>{suffix} | Score: {score:.0f} | {risk_tag}")
        lines.append(f"   💰 Entry: ₹{price:.2f} | SL: ₹{sl_price:.2f} (-{sl_pct:.1f}%) | RR: {rr}")
        lines.append(f"   🎯 TP1 (50% Book): ₹{tp1_price:.2f} (+{tp1_pct:.1f}%) | TP2 (Runner): ₹{tp2_price:.2f} (+{tp2_pct:.1f}%)")
        lines.append(f"   📊 RSI: {rsi_str} | ADX: {adx_str} | Vol: {vol_str} | Gap: +{gap:.2f}%")
        lines.append(f"   📈 Trend: {ema} | Day Chg: +{daily_chg:.2f}%" + (f" | {dist_str}" if dist_str else ""))
        lines.append(f"   🔑 Pattern: {pat_str}")
        lines.append(f"   💡 Why: {reasons[:100]}")
        catalyst = p.get("catalyst") or p.get("catalyst_headline")
        if catalyst:
            lines.append(f"   ⚡ Catalyst: {catalyst[:120]}")
        lines.append("   ⏰ Status: PENDING | Hold until: 15:30")
        lines.append("")

    lines.append("=" * 50)
    lines.append(f"🕐 Generated: {now_ist().strftime('%H:%M:%S')}")
    lines.append("\n⚠️ <i>Research only. Not a trade recommendation.</i>")

    ok = _send("\n".join(lines), review_with_grok=review_with_grok, event_type=audit_type)
    return ok


def send_research_picks(result: dict, accuracy: dict = None) -> bool:
    """
    Send the full research engine output:
    - Top trending sectors
    - AI deep analysis
    - Final picks with complete data
    """
    top_sectors  = result.get("top_sectors", [])
    final_picks  = result.get("final_picks", [])
    ai_analysis  = result.get("ai_analysis", "")

    if not final_picks:
        return send_no_picks("Research engine found no qualifying stocks")

    # Header message with sectors + AI analysis
    header_lines = [
        "🔬 <b>MARKETMIND RESEARCH REPORT</b>",
        f"📅 {now_ist().strftime('%d %b %Y, %H:%M IST')}",
        "",
        f"🏆 <b>Top Trending Sectors:</b> {' | '.join(top_sectors)}",
        "",
    ]
    if ai_analysis:
        header_lines.append(ai_analysis)
        header_lines.append("")

    _send("\n".join(header_lines), review_with_grok=False)

    # Then send full picks
    return send_morning_final_picks(final_picks, accuracy)


def send_eod_detailed_report(report: dict) -> bool:
    """Send detailed EOD report with reasons."""
    if not report:
        return True

    gainers = report.get("top_gainers", [])
    losers = report.get("top_losers", [])

    lines = [
        " DETAILED MARKET WRAP ",
        "="*50,
        f"Date: {report.get('date', '')}",
        "",
    ]

    lines.append("TOP 10 GAINERS:")
    for i, g in enumerate(gainers[:10], 1):
        lines.append(
            f"{i:>2}. <b>{g['symbol']}</b>: +{g['gain_pct']:>6.2f}% | ₹{g['price']}"
        )
        lines.append(f"    Sector: {g.get('sector', 'N/A')} | Reason: {g.get('reason', 'N/A')}")

    if losers:
        lines.append("")
        lines.append("TOP 10 LOSERS:")
        for i, l in enumerate(losers[:10], 1):
            lines.append(
                f"{i:>2}. <b>{l['symbol']}</b>: {l['gain_pct']:>6.2f}% | ₹{l['price']}"
            )
            lines.append(f"    Sector: {l.get('sector', 'N/A')} | Reason: {l.get('reason', 'N/A')}")

    lines.append("")
    lines.append("="*50)
    lines.append("\n⚠️ Research only. Not trade recommendation.")

    return _send("\n".join(lines))


def send_pick_status_update(tracking: dict, accuracy: dict = None) -> bool:
    """Send pick status update during day."""
    if not tracking:
        return True

    active = sum(1 for d in tracking.values() if d.get("status") == "active")
    tp_hit = sum(1 for d in tracking.values() if d.get("status") == "target_hit")
    sl_hit = sum(1 for d in tracking.values() if d.get("status") == "stopped_out")

    lines = [
        " Pick Status Update ",
        "="*40,
        f"Active: {active} | TP Hit: {tp_hit} | SL: {sl_hit}",
        "",
    ]

    for sym, data in tracking.items():
        status = data.get("status", "unknown")
        price = data.get("current_price", 0)
        pnl = data.get("pnl_pct", 0)
        if status == "active":
            lines.append(f"{sym}: ₹{price:.2f} ({pnl:+.2f}%)")

    if accuracy:
        lines.append("")
        lines.append(f"Bot Accuracy: {accuracy.get('accuracy_pct', 0)}%")

    lines.append("")
    lines.append("="*40)
    return _send("\n".join(lines))
