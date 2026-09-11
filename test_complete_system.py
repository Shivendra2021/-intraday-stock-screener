"""Test complete morning system."""
import sys
sys.path.insert(0, ".")

from modules.morning_analysis import generate_morning_report
from modules.stock_tracker import init_tracking, get_tracking_status
from modules.accuracy_tracker import init_accuracy_db, get_accuracy_stats
from modules.detailed_eod import generate_detailed_eod_report
from modules.alerts import (
    send_morning_health_check,
    send_morning_news,
    send_morning_final_picks,
    send_eod_detailed_report,
    send_pick_status_update
)

if __name__ == "__main__":
    print("=== Testing Morning Health Check ===")
    report = generate_morning_report()
    send_morning_health_check(report["system_health"])
    print(f"Health: {report['system_health']['status']}")

    print("\n=== Testing Morning News ===")
    send_morning_news(report)
    print(f"Sectors analyzed: {len(report['sector_trends'])}")

    print("\n=== Testing Accuracy ===")
    init_accuracy_db()
    stats = get_accuracy_stats(30)
    print(f"Accuracy (30d): {stats.get('accuracy_pct', 0)}%")
    print(f"Total picks: {stats.get('total_picks', 0)}")

    print("\n=== Testing EOD Report ===")
    eod = generate_detailed_eod_report()
    send_eod_detailed_report(eod)
    print(f"Top gainers: {len(eod['top_gainers'])}")

    print("\nDone - check Telegram for messages!")