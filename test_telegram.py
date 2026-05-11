# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
test_telegram.py — Send a test message to verify Telegram setup.
Usage: python test_telegram.py
"""

import os
import sys
from dotenv import load_dotenv

load_dotenv()

if __name__ == "__main__":
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")

    if not token or token == "your_bot_token_here":
        print("ERROR: TELEGRAM_BOT_TOKEN not set in .env")
        sys.exit(1)
    if not chat_id or chat_id == "your_chat_id_here":
        print("ERROR: TELEGRAM_CHAT_ID not set in .env")
        sys.exit(1)

    import requests
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text":    "✅ MarketMind Pro test message — setup successful!",
    }
    try:
        r = requests.post(url, json=payload, timeout=15)
        if r.status_code == 200:
            print("SUCCESS: Test message sent to Telegram!")
        else:
            print(f"ERROR: Telegram returned {r.status_code}: {r.text}")
            sys.exit(1)
    except Exception as e:
        print(f"ERROR: {e}")
        sys.exit(1)
