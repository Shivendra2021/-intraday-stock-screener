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
        "timestamp": datetime.datetime.now().isoformat(timespec="seconds"),
        "date": datetime.date.today().isoformat(),
        "event_type": event_type,
        "ok": bool(ok),
        "details": _safe_error_text(details)[:500],
    }
    try:
        with open("data/telegram_delivery.jsonl", "a", encoding="utf-8") as fp:
            fp.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
    except Exception as exc:
        logger.debug("Could not write Telegram audit: %s", exc)


def _send(text: str, review_with_grok: bool = True) -> bool:
    """
    Core Telegram send. Returns True on success.
    In DRY_RUN mode, logs the message and returns True.
    Includes retry logic with exponential backoff for rate limiting.
    """
    import time
    from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, DRY_RUN

    if DRY_RUN:
        logger.info(f"[DRY_RUN] Would send Telegram:\n{text}")
        _audit_send("telegram_message", True, "dry_run")
        return True

    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning("Telegram credentials not configured — skipping alert")
        _audit_send("telegram_message", False, "missing credentials")
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
    for attempt in range(max_retries):
        try:
            r = requests.post(url, json=payload, timeout=15)
            if r.status_code == 200:
                logger.info("Telegram message sent successfully")
                _audit_send("telegram_message", True, "sent")
                return True
            elif r.status_code == 429 or r.status_code == 503:
                # Rate limited — wait and retry
                wait_time = 2 ** attempt  # exponential backoff: 1s, 2s, 4s
                logger.warning(f"Telegram rate limited, retrying in {wait_time}s...")
                time.sleep(wait_time)
                continue
            else:
                logger.error(f"Telegram error {r.status_code}: {r.text[:200]}")
                _audit_send("telegram_message", False, f"{r.status_code}: {r.text[:200]}")
                return False
        except Exception as e:
            if attempt < max_retries - 1:
                wait_time = 2 ** attempt
                logger.warning("Telegram request failed, retrying in %ss: %s", wait_time, _safe_error_text(e))
                time.sleep(wait_time)
                continue
            logger.error("Telegram send failed after %s attempts: %s", max_retries, _safe_error_text(e))
            _audit_send("telegram_message", False, _safe_error_text(e))
            return False
    return False


def send_raw_alert(text: str, review_with_grok: bool = True) -> bool:
    """Public wrapper for sending a raw Telegram alert."""
    return _send(text, review_with_grok=review_with_grok)


# ─────────────────────────────────────────────────────────────────────────────
# Message builders
# ─────────────────────────────────────────────────────────────────────────────

def send_picks(picks: list, sentiment: float = 0.0) -> bool:
    """Send morning top-5 picks message."""
    date_str = datetime.date.today().strftime("%d %b %Y")

    if sentiment >= 0.3:
        sentiment_label = "🟢 Bullish"
    elif sentiment >= -0.1:
        sentiment_label = "🟡 Neutral"
    else:
        sentiment_label = "🔴 Bearish"

    lines = [f"📊 <b>MarketMind Pro — Top {len(picks)} Picks for {date_str}</b>\n"]
    for p in picks:
        upside = p.get("upside_pct", 0)
        conf   = p.get("score", p.get("confidence", 0))
        lines.append(
            f"{p['rank']}. <b>{p['symbol']}</b> — "
            f"Entry: ₹{p['entry_price']:.2f} | "
            f"SL: ₹{p['sl_price']:.2f} | "
            f"Target: ₹{p['target_price']:.2f} | "
            f"Upside: {upside:.1f}%"
        )

    avg_conf = sum(p.get("score", p.get("confidence", 0)) for p in picks) / max(len(picks), 1)
    lines.append(f"\nAvg Confidence: {avg_conf:.1f}%")
    lines.append(f"Market Sentiment: {sentiment_label}")
    lines.append("\n⚠️ <i>Research only. Not a trade recommendation.</i>")

    return _send("\n".join(lines))


def send_tp_hit(symbol: str, ret: float) -> bool:
    """Send target-hit notification."""
    text = (
        f"✅ <b>TARGET HIT</b>\n"
        f"<b>{symbol}</b> reached target\n"
        f"Return: <b>+{ret:.2f}%</b>"
    )
    return _send(text)


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
    date_str = datetime.date.today().strftime("%d %b %Y")
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
    date_str = datetime.date.today().strftime("%d %b %Y")
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


def send_no_picks(reason: str = "No stocks passed filters") -> bool:
    """Send notification when no picks generated today."""
    date_str = datetime.date.today().strftime("%d %b %Y")
    text = (
        f"📊 <b>MarketMind Pro — {date_str}</b>\n"
        f"\n⚠️ <b>No Picks Generated</b>\n"
        f"Reason: {reason}\n"
        f"\n<i>Market conditions may be unfavorable.</i>\n"
        f"<i>Bot is running - analysis complete.</i>"
    )
    return _send(text)


def send_heartbeat(universe_count: int, market_status: str, dry_run: bool, last_analysis: str = "N/A") -> bool:
    """Daily heartbeat - confirms bot is alive."""
    date_str = datetime.datetime.now().strftime("%d %b %Y %H:%M")
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
    date_str = datetime.datetime.now().strftime("%H:%M")
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
    date_str = datetime.datetime.now().strftime("%H:%M")
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

    date_str = datetime.date.today().strftime("%d %b %Y")

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


def send_morning_final_picks(picks: list, accuracy: dict = None, review_with_grok: bool = True) -> bool:
    """Send final morning picks with FULL technical data (RSI, ADX, EMA, prices)."""
    if not picks:
        return True

    lines = [
        "📊 <b>FINAL MORNING PICKS - " + datetime.datetime.now().strftime("%d %b %Y") + "</b>",
        "=" * 50,
        "",
    ]

    if accuracy:
        acc   = accuracy.get("accuracy_pct", 0)
        total = accuracy.get("total_picks", 0)
        tp    = accuracy.get("tp_hits", 0)
        sl    = accuracy.get("sl_hits", 0)
        lines.append(f"🎯 Bot Accuracy (30d): {acc}% | Total: {total} | ✅TP: {tp} | 🛑SL: {sl}")
        lines.append("")

    lines.append(f"📅 Date: {datetime.date.today().strftime('%Y-%m-%d')}")
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

        lines.append(f"{rank}. <b>{symbol}</b>" + (f" [{sector}]" if sector else "") + f" | Score: {score:.0f} | {risk_tag}")
        lines.append(f"   💰 Entry: ₹{price:.2f} | SL: ₹{sl_price:.2f} (-{sl_pct:.1f}%) | TP: ₹{target:.2f} (+{upside_pct:.1f}%) | RR: {rr}")
        lines.append(f"   📊 RSI: {rsi_str} | ADX: {adx_str} | Vol: {vol_str} | Gap: +{gap:.2f}%")
        lines.append(f"   📈 Trend: {ema} | Day Chg: +{daily_chg:.2f}%" + (f" | {dist_str}" if dist_str else ""))
        lines.append(f"   🔑 Pattern: {pat_str}")
        lines.append(f"   💡 Why: {reasons[:100]}")
        lines.append("   ⏰ Status: PENDING | Hold until: 15:30")
        lines.append("")

    lines.append("=" * 50)
    lines.append(f"🕐 Generated: {datetime.datetime.now().strftime('%H:%M:%S')}")
    lines.append("\n⚠️ <i>Research only. Not a trade recommendation.</i>")

    ok = _send("\n".join(lines), review_with_grok=review_with_grok)
    _audit_send("morning_final_picks", ok, f"count={len(picks)}")
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
        f"📅 {datetime.datetime.now().strftime('%d %b %Y, %H:%M IST')}",
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
