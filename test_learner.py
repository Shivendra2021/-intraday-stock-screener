# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
test_learner.py — Unit tests for market_learner logic.
Tests: pattern key building, exponential smoothing, anti-pattern detection.
Usage: python test_learner.py
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from modules.market_learner import _build_pattern_key, _smooth_rate

ERRORS = []


def test(name, condition, detail=""):
    if condition:
        print(f"  PASS: {name}")
    else:
        print(f"  FAIL: {name}" + (f": {detail}" if detail else ""))
        ERRORS.append(name)


#
# Test 1: Pattern key building
#

def test_pattern_keys():
    print("\n  [Pattern Key Tests]")

    # Case: RSI=52, vol_ratio=2.5, MACD_pos, EMA_full_bull
    key = _build_pattern_key(52.0, 2.5, 0.5, 0.3, "EMA_full_bull")
    test("RSI_50to55 bucket", "RSI_50to55" in key, key)
    test("VOL_veryhigh bucket", "VOL_veryhigh" in key, key)
    test("MACD_pos bucket", "MACD_pos" in key, key)
    test("EMA_full_bull bucket", "EMA_full_bull" in key, key)

    # Case: RSI=35, vol_ratio=0.5, MACD_neg, EMA_bear
    key2 = _build_pattern_key(35.0, 0.5, -0.2, 0.1, "EMA_bear")
    test("RSI_under40 bucket", "RSI_under40" in key2, key2)
    test("VOL_low bucket", "VOL_low" in key2, key2)
    test("MACD_neg bucket (macd < sig)", "MACD_neg" in key2, key2)

    # Determinism: same inputs -> same key
    k1 = _build_pattern_key(60.0, 1.5, 0.8, 0.5, "EMA_partial_bull")
    k2 = _build_pattern_key(60.0, 1.5, 0.8, 0.5, "EMA_partial_bull")
    test("Pattern key is deterministic", k1 == k2, f"k1={k1}, k2={k2}")

    # Boundary: RSI exactly 70 -> RSI_over70
    key3 = _build_pattern_key(70.0, 1.0, 0, 0, "EMA_bear")
    test("RSI=70 -> RSI_over70", "RSI_over70" in key3, key3)


#
# Test 2: Exponential smoothing
#

def test_smoothing():
    print("\n  [Exponential Smoothing Tests]")

    # sample_count < 10: alpha = 0.5
    result = _smooth_rate(0.8, 0.4, 5)
    expected = 0.5 * 0.8 + 0.5 * 0.4  # 0.60
    test("Small sample smoothing (alpha=0.5)", abs(result - expected) < 1e-6,
         f"got={result:.4f}, expected={expected:.4f}")

    # sample_count >= 10: alpha = 0.3
    result2 = _smooth_rate(0.8, 0.4, 15)
    expected2 = 0.7 * 0.8 + 0.3 * 0.4  # 0.68
    test("Large sample smoothing (alpha=0.3)", abs(result2 - expected2) < 1e-6,
         f"got={result2:.4f}, expected={expected2:.4f}")

    # Old rate 0.0, today 1.0 -> should be 0.5 for small sample
    result3 = _smooth_rate(0.0, 1.0, 1)
    test("Zero -> one smoothing", abs(result3 - 0.5) < 1e-6, f"got={result3:.4f}")

    # Both same rate -> stays same
    result4 = _smooth_rate(0.65, 0.65, 20)
    test("Same rate stays same", abs(result4 - 0.65) < 1e-6, f"got={result4:.4f}")


#
# Test 3: Anti-pattern logic simulation
#

def test_anti_pattern():
    print("\n  [Anti-Pattern Detection Tests]")

    from modules.market_learner import ANTI_PATTERN_LOSER_SHARE, ANTI_PATTERN_WINNER_SHARE

    # Simulate: pattern appears in 40% of losers, 10% of winners -> anti-pattern
    total_w  = 50
    total_l  = 50
    w_count  = 5   # 10% of winners
    l_count  = 20  # 40% of losers

    w_share = w_count / total_w
    l_share = l_count / total_l
    is_anti = (l_share >= ANTI_PATTERN_LOSER_SHARE and w_share < ANTI_PATTERN_WINNER_SHARE)
    test("Pattern is flagged as anti-pattern (high loser, low winner)",
         is_anti, f"l_share={l_share:.2f}, w_share={w_share:.2f}")

    # Should NOT be anti-pattern: balanced
    w_count2 = 20  # 40% of winners
    l_count2 = 20  # 40% of losers
    w_share2 = w_count2 / total_w
    l_share2 = l_count2 / total_l
    is_anti2 = (l_share2 >= ANTI_PATTERN_LOSER_SHARE and w_share2 < ANTI_PATTERN_WINNER_SHARE)
    test("Balanced pattern is NOT anti-pattern", not is_anti2,
         f"l_share={l_share2:.2f}, w_share={w_share2:.2f}")


#
# Run all
#

if __name__ == "__main__":
    print("\n" + "="*50)
    print("  Learner Unit Tests")
    print("="*50)

    test_pattern_keys()
    test_smoothing()
    test_anti_pattern()

    print(f"\n  {'All tests passed!' if not ERRORS else f'{len(ERRORS)} test(s) failed!'}")
    if ERRORS:
        print(f"  Failed: {ERRORS}")
    print("="*50 + "\n")
    sys.exit(0 if not ERRORS else 1)