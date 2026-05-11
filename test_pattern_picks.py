from modules.pattern_researcher import generate_picks_for_tomorrow
from modules.alerts import send_pattern_picks

picks = generate_picks_for_tomorrow(5)

print("=== Generated Tomorrow's Picks ===")
for p in picks:
    print(f"{p['rank']}. {p['symbol']}: Price={p['current_price']} Change={p['change_pct']}% Vol={p['volume_ratio']}x Score={p['score']}")

print("\nSending to Telegram...")
send_pattern_picks(picks)
print("Done!")