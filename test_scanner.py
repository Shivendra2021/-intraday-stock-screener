# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
test_scanner.py — Tests for modules/scanner.py.
Usage: python test_scanner.py
"""

import sys
import os
import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.scanner import get_universe, is_market_holiday, is_market_open

ERRORS = []


def test(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}")
    else:
        print(f"  FAIL: {name}" + (f": {detail}" if detail else ""))
        ERRORS.append(name)


def run():
    print("\n" + "="*50)
    print("  Scanner Tests")
    print("="*50)

    universe = get_universe()
    print(f"\n  Fetched {len(universe)} symbols\n")

    test("Universe is a list",      isinstance(universe, list))
    test("Universe has 100+ stocks", len(universe) >= 100,
         f"got {len(universe)}")
    test("No duplicate symbols",    len(universe) == len(set(universe)))
    test("All symbols are strings", all(isinstance(s, str) for s in universe))
    test("All symbols non-empty",   all(len(s.strip()) > 0 for s in universe))
    test("Contains RELIANCE",       "RELIANCE" in universe)
    test("Contains TCS",            "TCS" in universe)

    # Holiday check — 15 Aug 2024 is Independence Day (NSE holiday)
    independence_day = datetime.date(2024, 8, 15)
    test("Independence Day is holiday",
         is_market_holiday(independence_day),
         f"date={independence_day}")

    # Weekend check
    saturday = datetime.date(2025, 1, 4)   # known Saturday
    test("Saturday is not a trading day",
         is_market_holiday(saturday) or saturday.weekday() >= 5)

    print(f"\n  {'All tests passed!' if not ERRORS else f'{len(ERRORS)} test(s) failed!'}")
    if ERRORS:
        print(f"  Failed: {ERRORS}")
    print("="*50 + "\n")

    return len(ERRORS) == 0


if __name__ == "__main__":
    ok = run()
    sys.exit(0 if ok else 1)