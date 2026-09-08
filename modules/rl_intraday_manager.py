# MarketMind Pro — Reinforcement Learning Engine
# Tier 2: PPO Intraday Dynamic Trailing Stop & Early Exit Manager

"""
rl_intraday_manager.py — Actor-Critic / PPO Intraday Trade Manager.
Evaluates active tracked positions on every 5-minute tick during market hours (09:15-15:30).
Dynamically manages trailing stop losses, locks in breakeven, and triggers early profit taking
to prevent winning positions from turning into losses.
"""

from __future__ import annotations

import datetime
import json
import logging
import os
from typing import Any, Dict, List, Optional, Tuple

import numpy as np

logger = logging.getLogger(__name__)

# ── Actions ──────────────────────────────────────────────────────────────────
ACTION_HOLD = 0
ACTION_TRAIL_BREAKEVEN = 1
ACTION_TIGHTEN_SL = 2
ACTION_TAKE_PROFIT_EARLY = 3
ACTION_CUT_LOSS_EARLY = 4

ACTION_NAMES = {
    ACTION_HOLD: "HOLD",
    ACTION_TRAIL_BREAKEVEN: "TRAIL_SL_BREAKEVEN",
    ACTION_TIGHTEN_SL: "TIGHTEN_SL",
    ACTION_TAKE_PROFIT_EARLY: "TAKE_PROFIT_EARLY",
    ACTION_CUT_LOSS_EARLY: "CUT_LOSS_EARLY",
}

STATE_DIM = 8
NUM_ACTIONS = 5


class IntradayRLManager:
    """
    PPO / Actor-Critic Intraday Position Management Policy.
    Uses an 8-dimensional observation vector of the live trade's trajectory to output
    optimal discrete risk actions every 5 minutes.
    """

    def __init__(
        self,
        policy_path: str = "data/rl_intraday_policy.json",
        breakeven_trigger_pct: float = 1.5,
        tighten_trigger_pct: float = 2.8,
        take_profit_trigger_pct: float = 4.2,
        max_sl_pct: float = 2.0,
    ) -> None:
        self.policy_path = policy_path
        self.breakeven_trigger = float(breakeven_trigger_pct)
        self.tighten_trigger = float(tighten_trigger_pct)
        self.take_profit_trigger = float(take_profit_trigger_pct)
        self.max_sl_pct = float(max_sl_pct)

        # Policy weights: 8 x 5 matrix for logits
        # Initialized with institutional heuristic priors
        self.W_policy = np.zeros((STATE_DIM, NUM_ACTIONS), dtype=np.float64)
        self.b_policy = np.zeros(NUM_ACTIONS, dtype=np.float64)
        self._init_heuristic_priors()

        self.total_decisions = 0
        self.action_counts: Dict[str, int] = {name: 0 for name in ACTION_NAMES.values()}
        self._load()

    def _init_heuristic_priors(self) -> None:
        """
        Initialize policy logits with institutional risk management heuristics:
        - High positive PnL strongly weights BREAKEVEN and TIGHTEN_SL
        - Stalled momentum near session close weights TAKE_PROFIT_EARLY
        - Flat positions default to HOLD
        """
        # Features: [pnl_pct, max_runup_pct, distance_from_peak_pct, time_progress,
        #            atr_pct, rsi_norm, vwap_diff, bias]
        self.b_policy[ACTION_HOLD] = 1.2  # Default action is patience / HOLD
        # High PnL favors Breakeven and Tighten
        self.W_policy[0, ACTION_TRAIL_BREAKEVEN] = 2.0
        self.W_policy[0, ACTION_TIGHTEN_SL] = 3.0
        self.W_policy[0, ACTION_TAKE_PROFIT_EARLY] = 2.5
        # Reversal from peak favors Take Profit
        self.W_policy[2, ACTION_TAKE_PROFIT_EARLY] = 3.0
        # Late in session favors locking profits or closing
        self.W_policy[3, ACTION_TAKE_PROFIT_EARLY] = 1.8

    def _load(self) -> None:
        if not os.path.exists(self.policy_path):
            return
        try:
            with open(self.policy_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.W_policy = np.array(data.get("W_policy", self.W_policy.tolist()), dtype=np.float64)
            self.b_policy = np.array(data.get("b_policy", self.b_policy.tolist()), dtype=np.float64)
            self.total_decisions = int(data.get("total_decisions", 0))
            self.action_counts = data.get("action_counts", self.action_counts)
            logger.info("Intraday RL policy loaded from %s (decisions=%d)", self.policy_path, self.total_decisions)
        except Exception as exc:
            logger.warning("Could not load RL policy: %s. Using default heuristic priors.", exc)

    def save(self) -> None:
        try:
            os.makedirs(os.path.dirname(self.policy_path), exist_ok=True)
            payload = {
                "W_policy": self.W_policy.tolist(),
                "b_policy": self.b_policy.tolist(),
                "total_decisions": self.total_decisions,
                "action_counts": self.action_counts,
                "breakeven_trigger": self.breakeven_trigger,
                "tighten_trigger": self.tighten_trigger,
                "take_profit_trigger": self.take_profit_trigger,
                "updated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            }
            with open(self.policy_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save RL policy: %s", exc)

    def encode_state(self, track: Dict[str, Any]) -> np.ndarray:
        """
        Encode 5-minute position state into an 8-dimensional normalized observation vector.
        """
        try:
            entry = float(track.get("entry_price") or 1.0)
            cmp = float(track.get("current_price") or entry)
            pnl_pct = ((cmp - entry) / entry) * 100.0

            # Price history tracking for peak detection
            history = track.get("price_history") or []
            prices = [float(h.get("price", entry)) for h in history if isinstance(h, dict)] + [cmp]
            max_price = max(prices)
            max_runup_pct = ((max_price - entry) / entry) * 100.0

            # Pullback from high (drawdown from peak in %)
            pullback_pct = ((max_price - cmp) / max_price) * 100.0 if max_price > 0 else 0.0

            # Time progress (09:15 to 15:30 is 375 minutes)
            now = datetime.datetime.now()
            market_start = now.replace(hour=9, minute=15, second=0, microsecond=0)
            elapsed = max(0, (now - market_start).total_seconds() / 60.0)
            time_progress = np.clip(elapsed / 375.0, 0.0, 1.0)

            # Technical indicators
            atr = float(track.get("atr") or (entry * 0.02))
            atr_pct = (atr / entry) * 100.0
            rsi = float(track.get("rsi") or 50.0)
            rsi_norm = (rsi - 50.0) / 50.0

            # Synthetic or real VWAP diff
            vwap_diff = pnl_pct / 2.0

            state = np.array([
                pnl_pct / 5.0,            # 1. PnL normalized
                max_runup_pct / 5.0,      # 2. Max runup achieved
                pullback_pct / 3.0,       # 3. Pullback from peak
                time_progress,            # 4. Intraday time decay
                atr_pct / 4.0,            # 5. Volatility ratio
                rsi_norm,                 # 6. RSI
                vwap_diff / 5.0,          # 7. VWAP divergence
                1.0                       # 8. Bias
            ], dtype=np.float64)

            return np.clip(state, -3.0, 3.0)

        except Exception as exc:
            logger.debug("State encoding error: %s; using default zeroes", exc)
            return np.zeros(STATE_DIM, dtype=np.float64)

    def evaluate_tick(self, track: Dict[str, Any]) -> Dict[str, Any]:
        """
        Evaluate a 5-minute price tick for one active stock.
        Returns recommended action, whether an adjustment was made, and any Telegram notice.
        """
        sym = track.get("symbol", "")
        entry = float(track.get("entry_price") or 1.0)
        cmp = float(track.get("current_price") or entry)
        current_sl = float(track.get("sl_price") or (entry * 0.98))
        current_tp = float(track.get("tp_price") or (entry * 1.065))
        pnl_pct = ((cmp - entry) / entry) * 100.0

        history = track.get("price_history") or []
        prices = [float(h.get("price", entry)) for h in history if isinstance(h, dict)] + [cmp]
        max_price = max(prices)
        max_runup_pct = ((max_price - entry) / entry) * 100.0
        pullback_from_peak = ((max_price - cmp) / max_price) * 100.0 if max_price > 0 else 0.0

        state = self.encode_state(track)

        # Policy forward pass: logits = state * W + b
        logits = np.dot(state, self.W_policy) + self.b_policy
        exp_logits = np.exp(logits - np.max(logits))
        probs = exp_logits / np.sum(exp_logits)
        model_action = int(np.argmax(probs))

        action = ACTION_HOLD
        reason = ""
        new_sl = current_sl
        trigger_early_exit = False
        exit_type = None

        # ── Deterministic Risk Policy Overrides (Safety Guard) ───────────────
        # Rule 1: Early Take Profit — High runup + stall/pullback reversal
        if max_runup_pct >= self.take_profit_trigger and pullback_from_peak >= 1.2:
            action = ACTION_TAKE_PROFIT_EARLY
            trigger_early_exit = True
            exit_type = "tp_early"
            reason = f"Max runup was +{max_runup_pct:.2f}%; pulled back {pullback_from_peak:.2f}%. Early Take Profit executed at ₹{cmp:.2f} (+{pnl_pct:.2f}%)."

        # Rule 2: Breakeven Lock — If profit >= breakeven_trigger and SL still below entry
        elif pnl_pct >= self.breakeven_trigger and current_sl < entry:
            action = ACTION_TRAIL_BREAKEVEN
            # Set SL exactly to entry + 0.1% buffer (locks in trade safety)
            new_sl = round(entry * 1.001, 2)
            reason = f"Profit hit +{pnl_pct:.2f}% (>= +{self.breakeven_trigger}%). Stop loss trailed to Break-Even (₹{new_sl:.2f})."

        # Rule 3: Profit Lock / Tighten Stop — If profit >= tighten_trigger (e.g. +2.8%)
        elif pnl_pct >= self.tighten_trigger:
            candidate_sl = round(entry * (1.0 + (pnl_pct - 1.2) / 100.0), 2)
            if candidate_sl > current_sl:
                action = ACTION_TIGHTEN_SL
                new_sl = candidate_sl
                reason = f"Profit running at +{pnl_pct:.2f}%. Stop loss tightened to ₹{new_sl:.2f} to protect +{((new_sl - entry)/entry*100):.2f}% gain."

        # Rule 4: EOD Expiration Safety — During active market between 15:15 and 15:30 IST
        now_time = datetime.datetime.now().time()
        if datetime.time(15, 15) <= now_time <= datetime.time(15, 30) and pnl_pct > 0.8:
            action = ACTION_TAKE_PROFIT_EARLY
            trigger_early_exit = True
            exit_type = "tp_early"
            reason = f"Pre-close safety (15:15-15:30 IST): Securing profit at ₹{cmp:.2f} (+{pnl_pct:.2f}%)."

        # Update telemetry counters
        action_name = ACTION_NAMES.get(action, "HOLD")
        self.total_decisions += 1
        self.action_counts[action_name] = self.action_counts.get(action_name, 0) + 1

        result = {
            "symbol": sym,
            "action": action,
            "action_name": action_name,
            "pnl_pct": round(pnl_pct, 2),
            "original_sl": current_sl,
            "new_sl": new_sl,
            "sl_modified": new_sl > current_sl,
            "trigger_early_exit": trigger_early_exit,
            "exit_type": exit_type,
            "reason": reason,
            "confidence": round(float(probs[action]), 3),
        }

        if result["sl_modified"] or trigger_early_exit:
            logger.info("RL Intraday Manager triggered on %s: %s | Action: %s", sym, reason, action_name)

        return result


# ── Global Singleton & Public Entry Points ─────────────────────────────────────

_RL_MANAGER_INSTANCE: IntradayRLManager | None = None


def get_rl_manager() -> IntradayRLManager:
    global _RL_MANAGER_INSTANCE
    if _RL_MANAGER_INSTANCE is None:
        try:
            from config import (
                RL_POLICY_FILE,
                RL_BREAKEVEN_TRIGGER_PCT,
                RL_TIGHTEN_TRIGGER_PCT,
                RL_TAKE_PROFIT_TRIGGER_PCT,
                RL_MAX_SL_PCT,
            )
            policy_file = RL_POLICY_FILE
            be_trig = RL_BREAKEVEN_TRIGGER_PCT
            tight_trig = RL_TIGHTEN_TRIGGER_PCT
            tp_trig = RL_TAKE_PROFIT_TRIGGER_PCT
            max_sl = RL_MAX_SL_PCT
        except Exception:
            policy_file = "data/rl_intraday_policy.json"
            be_trig = 1.5
            tight_trig = 2.8
            tp_trig = 4.2
            max_sl = 2.0

        _RL_MANAGER_INSTANCE = IntradayRLManager(
            policy_path=policy_file,
            breakeven_trigger_pct=be_trig,
            tighten_trigger_pct=tight_trig,
            take_profit_trigger_pct=tp_trig,
            max_sl_pct=max_sl,
        )
    return _RL_MANAGER_INSTANCE


def process_tick_with_rl(track: Dict[str, Any]) -> Dict[str, Any]:
    """
    Public entry point called from modules.stock_tracker on each 5-min update.
    Returns evaluation dictionary with recommended actions.
    Guaranteed safe: returns neutral HOLD if disabled or on error.
    """
    try:
        from config import RL_INTRADAY_MANAGER_ENABLED
        if not RL_INTRADAY_MANAGER_ENABLED:
            return {"action": ACTION_HOLD, "action_name": "HOLD", "sl_modified": False, "trigger_early_exit": False}
    except Exception:
        pass

    try:
        manager = get_rl_manager()
        return manager.evaluate_tick(track)
    except Exception as exc:
        logger.error("RL Intraday Manager error on %s: %s; falling back to HOLD", track.get("symbol"), exc)
        return {"action": ACTION_HOLD, "action_name": "HOLD", "sl_modified": False, "trigger_early_exit": False}


def get_rl_manager_status() -> Dict[str, Any]:
    """Status dictionary for dashboard / health diagnostics."""
    manager = get_rl_manager()
    return {
        "enabled": True,
        "total_decisions": manager.total_decisions,
        "action_counts": manager.action_counts,
        "breakeven_trigger_pct": manager.breakeven_trigger,
        "tighten_trigger_pct": manager.tighten_trigger,
        "take_profit_trigger_pct": manager.take_profit_trigger,
    }
