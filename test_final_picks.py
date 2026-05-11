"""Test morning final picks with accuracy."""
import sys
sys.path.insert(0, ".")

from modules.pattern_researcher import generate_picks_for_tomorrow
from modules.accuracy_tracker import init_accuracy_db, get_accuracy_stats
from modules.alerts import send_morning_final_picks

init_accuracy_db()

# Generate picks
picks = generate_picks_for_tomorrow(5)

# Get accuracy
accuracy = get_accuracy_stats(30)

# Send to Telegram
send_morning_final_picks(picks, accuracy)

print("=== Final Morning Picks ===")
for p in picks:
    print(f"{p['rank']}. {p['symbol']}: Price={p['current_price']} Change={p['change_pct']}% Vol={p['volume_ratio']}x")

print(f"\nBot Accuracy (30d): {accuracy.get('accuracy_pct', 0)}%")
print(f"Total Picks: {accuracy.get('total_picks', 0)}")
print(f"TP Hits: {accuracy.get('tp_hits', 0)}")
print(f"SL Hits: {accuracy.get('sl_hits', 0)}")
print("\nSent to Telegram!")