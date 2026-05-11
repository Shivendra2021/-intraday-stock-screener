"""Test end-of-day report manually."""
import sys
sys.path.insert(0, ".")

from modules.tracker import _get_top10_performers
from modules.alerts import send_end_of_day_report

print("Scanning top 10 performers (this takes 1-2 minutes)...")
performers = _get_top10_performers()

print(f"Found {len(performers['gainers'])} gainers, {len(performers['losers'])} losers")

print("\nSending to Telegram...")
send_end_of_day_report(performers)
print("Done!")