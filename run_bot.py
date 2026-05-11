# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
run_bot.py — Simple launcher for MarketMind Pro.
Usage: python run_bot.py
"""

import os
import sys
import multiprocessing

# Ensure project root is on path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv
load_dotenv()

if __name__ == "__main__":
    multiprocessing.freeze_support()  # Windows multiprocessing requirement
    print("Starting MarketMind Pro...")

    # Validate critical directories exist
    for d in ["data", "logs", "output", "modules"]:
        if not os.path.exists(d):
            print(f"  Directory '{d}' missing. Running init_system.py first...")
            import subprocess
            subprocess.run([sys.executable, "init_system.py"])
            break

    try:
        from main import main
        main()
    except KeyboardInterrupt:
        print("\nMarketMind Pro stopped cleanly.")
    except Exception as e:
        print(f"\nFatal error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
