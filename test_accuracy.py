"""Test accuracy by recording sample picks."""
import sys
sys.path.insert(0, ".")

from modules.accuracy_tracker import init_accuracy_db, record_pick, update_pick_status, get_accuracy_stats

# Initialize
init_accuracy_db()

# Record some test picks (this simulates what the bot will do daily)
test_picks = [
    {"symbol": "INFY", "entry_price": 1500, "sl_price": 1455, "target_price": 1575},
    {"symbol": "TCS", "entry_price": 4000, "sl_price": 3900, "target_price": 4200},
    {"symbol": "HDFCBANK", "entry_price": 1800, "sl_price": 1750, "target_price": 1900},
]

for pick in test_picks:
    record_pick(pick, sector="IT")

# Simulate outcomes (TP hit, SL hit, hold)
update_pick_status("INFY", "target_hit", exit_price=1575, pnl=5.0)
update_pick_status("TCS", "stopped_out", exit_price=3900, pnl=-2.5)

# Get accuracy
stats = get_accuracy_stats(30)

print("=== Accuracy Test ===")
print(f"Total Picks: {stats['total_picks']}")
print(f"TP Hits: {stats['tp_hits']}")
print(f"SL Hits: {stats['sl_hits']}")
print(f"Holds: {stats['holds']}")
print(f"Accuracy: {stats['accuracy_pct']}%")
print(f"Average P&L: {stats['avg_pnl']}%")
print(f"Sector Performance: {stats['sector_performance']}")