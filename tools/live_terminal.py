"""Visible live terminal for Stock Analyser V2."""

from __future__ import annotations

import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

for stream in (sys.stdout, sys.stderr):
    if hasattr(stream, "reconfigure"):
        stream.reconfigure(encoding="utf-8", errors="replace")

from modules.terminal_updater import get_terminal_state, refresh_terminal_state


def _money(value) -> str:
    try:
        return f"Rs {float(value):,.2f}"
    except Exception:
        return "Rs --"


def _pct(value) -> str:
    try:
        number = float(value)
        return f"{number:+.2f}%"
    except Exception:
        return "--"


def _line(char: str = "=", width: int = 78) -> str:
    return char * width


def _clear() -> None:
    os.system("cls" if os.name == "nt" else "clear")


def _print_picks(state: dict) -> None:
    picks = state.get("today_picks") or []
    print("TODAY MORNING PICKS")
    print(_line("-"))
    if not picks:
        print("Blank until today's morning analysis stores picks in the database.")
        print()
        return
    print(f"{'R':<3} {'SYMBOL':<14} {'CONF':>6} {'ENTRY':>12} {'SL':>12} {'TP':>12} {'STATUS':>12}")
    for row in picks[:5]:
        print(
            f"{row.get('rank') or '-':<3} "
            f"{str(row.get('symbol') or ''):<14} "
            f"{float(row.get('confidence') or 0):>5.0f}% "
            f"{_money(row.get('entry_price')):>12} "
            f"{_money(row.get('sl_price')):>12} "
            f"{_money(row.get('target_price')):>12} "
            f"{str(row.get('status') or 'open')[:12]:>12}"
        )
    print()


def _print_ai(state: dict) -> None:
    ai = state.get("ai_brief") or {}
    print("AI TERMINAL BRIEF")
    print(_line("-"))
    print(f"Model: {ai.get('model') or 'local/db state'} | Updated: {ai.get('updated_at') or '--'}")
    for key in ("market_note", "dashboard_summary", "pick_view"):
        text = ai.get(key)
        if text:
            print(f"- {text}")
    risks = ai.get("risk_flags") or []
    actions = ai.get("action_items") or []
    if risks:
        print("Risks: " + "; ".join(str(x) for x in risks[:4]))
    if actions:
        print("Actions: " + "; ".join(str(x) for x in actions[:4]))
    print()


def _print_learning(state: dict) -> None:
    ollama = state.get("ollama") or {}
    print("LEARNING / TOP MOVER AGENT")
    print(_line("-"))
    print(f"Scanned: {ollama.get('scanned') or 0} | Winners: {ollama.get('winners') or 0}")
    symbols = ollama.get("top_symbols") or []
    if symbols:
        print("Top symbols: " + ", ".join(str(x) for x in symbols[:8]))
    if ollama.get("summary"):
        print(str(ollama.get("summary"))[:260])
    print()


def _print_accuracy(state: dict) -> None:
    rows = state.get("accuracy") or []
    print("RECENT ACCURACY")
    print(_line("-"))
    if not rows:
        print("No daily accuracy rows yet.")
        print()
        return
    print(f"{'DATE':<12} {'TP':>4} {'SL':>4} {'ACC':>8} {'AVG RET':>9}")
    for row in rows[:7]:
        print(
            f"{str(row.get('date') or ''):<12} "
            f"{int(row.get('tp_count') or 0):>4} "
            f"{int(row.get('sl_count') or 0):>4} "
            f"{float(row.get('accuracy') or 0):>7.1f}% "
            f"{_pct(row.get('avg_return')):>9}"
        )
    print()


def _print_history(state: dict) -> None:
    rows = state.get("recent_history") or []
    print("RECENT PICK HISTORY")
    print(_line("-"))
    if not rows:
        print("No history yet.")
        return
    for row in rows[:8]:
        print(
            f"{row.get('date') or '--'} | "
            f"{str(row.get('symbol') or ''):<12} | "
            f"{str(row.get('status') or 'open'):<10} | "
            f"{_pct(row.get('result_return'))}"
        )


def render(state: dict) -> None:
    _clear()
    print(_line())
    print("  Stock Analyser V2 - AI Live Terminal")
    print("  DB-backed view. Refreshes while your bot/dashboard update data.")
    print(_line())
    print(
        f"Date: {state.get('date')} | Market: {state.get('market_status')} | "
        f"Universe: {state.get('universe_count')} | Updated: {state.get('updated_at')}"
    )
    print(_line())
    print()
    _print_picks(state)
    _print_ai(state)
    _print_learning(state)
    _print_accuracy(state)
    _print_history(state)
    print()
    print(_line())
    print("Press Ctrl+C to stop this terminal view. Bot/dashboard can keep running.")


def main() -> None:
    interval = int(os.getenv("LIVE_TERMINAL_REFRESH_SECONDS", "15"))
    while True:
        state = refresh_terminal_state()
        render(state)
        time.sleep(max(5, interval))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nLive terminal stopped.\n")
