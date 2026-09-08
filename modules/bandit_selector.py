# MarketMind Pro — Reinforcement Learning Engine
# Tier 1: Contextual Multi-Armed Bandit (LinUCB) for Morning Candidate Selection

"""
bandit_selector.py — Contextual Multi-Armed Bandit using LinUCB (Linear Upper Confidence Bound).
Selects and ranks morning candidates from 20 -> Top 5 based on multi-dimensional feature
contexts and learned EOD risk-adjusted rewards.
"""

from __future__ import annotations

import json
import logging
import os
from typing import Any, Dict, List, Tuple

import numpy as np

logger = logging.getLogger(__name__)

FEATURE_NAMES = [
    "gap_pct_norm",
    "rsi_norm",
    "vol_ratio_norm",
    "atr_pct_norm",
    "macd_signal_align",
    "score_norm",
    "sector_momentum_norm",
    "intercept_bias",
]
FEATURE_DIM = len(FEATURE_NAMES)


class ContextualBandit:
    """
    LinUCB (Disjoint/Shared Linear Models) Contextual Bandit.
    Balances exploitation of proven high-reward feature signatures with
    exploration of high-uncertainty candidate profiles.
    """

    def __init__(self, alpha: float = 0.25, weights_path: str = "data/bandit_weights.json") -> None:
        self.alpha = float(alpha)
        self.weights_path = weights_path
        self.dim = FEATURE_DIM
        self.A = np.identity(self.dim, dtype=np.float64)
        self.b = np.zeros((self.dim, 1), dtype=np.float64)
        self.total_pulls = 0
        self.total_rewards = 0.0
        self.last_updated = ""
        self._load()

    def _load(self) -> None:
        """Load persisted covariance matrix and reward vectors."""
        if not os.path.exists(self.weights_path):
            return
        try:
            with open(self.weights_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self.A = np.array(data.get("A", np.identity(self.dim).tolist()), dtype=np.float64)
            self.b = np.array(data.get("b", np.zeros((self.dim, 1)).tolist()), dtype=np.float64)
            self.total_pulls = int(data.get("total_pulls", 0))
            self.total_rewards = float(data.get("total_rewards", 0.0))
            self.last_updated = str(data.get("last_updated", ""))
            logger.info("Contextual Bandit weights loaded (pulls=%d)", self.total_pulls)
        except Exception as exc:
            logger.warning("Could not load bandit weights: %s. Using default identity prior.", exc)
            self.A = np.identity(self.dim, dtype=np.float64)
            self.b = np.zeros((self.dim, 1), dtype=np.float64)

    def save(self) -> None:
        """Persist covariance matrix and reward vectors to JSON."""
        try:
            os.makedirs(os.path.dirname(self.weights_path), exist_ok=True)
            payload = {
                "A": self.A.tolist(),
                "b": self.b.tolist(),
                "total_pulls": self.total_pulls,
                "total_rewards": round(self.total_rewards, 4),
                "last_updated": self.last_updated,
                "feature_names": FEATURE_NAMES,
            }
            with open(self.weights_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
        except Exception as exc:
            logger.error("Failed to save bandit weights: %s", exc)

    def extract_features(self, candidate: Dict[str, Any]) -> np.ndarray:
        """Extract a normalized d-dimensional feature vector from a candidate dictionary."""
        try:
            price = float(candidate.get("price") or candidate.get("entry_price") or 100.0)
            atr = float(candidate.get("atr") or (price * 0.02))

            # 1. Gap pct (-5% to +5% -> normalized -1 to +1)
            gap = float(candidate.get("gap_pct") or candidate.get("change_pct") or 0.0)
            gap_norm = float(np.clip(gap / 5.0, -1.0, 1.0))

            # 2. RSI (0 to 100 -> centered around 50 -> -1 to +1)
            rsi = float(candidate.get("rsi") or 55.0)
            rsi_norm = float(np.clip((rsi - 50.0) / 50.0, -1.0, 1.0))

            # 3. Volume ratio (0 to 4.0 -> normalized 0 to 1)
            vol_ratio = float(candidate.get("volume_ratio") or candidate.get("vol_ratio") or 1.0)
            vol_norm = float(np.clip(vol_ratio / 4.0, 0.0, 1.0))

            # 4. ATR percentage (0 to 8% -> normalized 0 to 1)
            atr_pct = (atr / max(price, 1.0)) * 100.0
            atr_norm = float(np.clip(atr_pct / 8.0, 0.0, 1.0))

            # 5. MACD alignment
            macd = candidate.get("macd")
            if isinstance(macd, dict):
                macd_sig = 1.0 if float(macd.get("macd", 0)) >= float(macd.get("signal", 0)) else -1.0
            elif isinstance(macd, (int, float)):
                macd_sig = 1.0 if macd >= 0 else -1.0
            else:
                macd_sig = 1.0 if "MACD_pos" in str(candidate.get("pattern_key", "")) else -0.5

            # 6. Pre-existing score (0 to 100 -> 0 to 1)
            score = float(candidate.get("score") or candidate.get("confidence") or 50.0)
            score_norm = float(np.clip(score / 100.0, 0.0, 1.0))

            # 7. Sector momentum score (0 to 1)
            sector_score = float(candidate.get("sector_score") or candidate.get("sector_rank") or 0.5)
            if sector_score > 1.0:
                sector_score = sector_score / 100.0
            sector_norm = float(np.clip(sector_score, 0.0, 1.0))

            # 8. Constant intercept bias
            bias = 1.0

            vec = np.array(
                [gap_norm, rsi_norm, vol_norm, atr_norm, macd_sig, score_norm, sector_norm, bias],
                dtype=np.float64,
            ).reshape(-1, 1)
            return vec

        except Exception as exc:
            logger.debug("Feature extraction error: %s; returning zero vector", exc)
            return np.zeros((self.dim, 1), dtype=np.float64)

    def calculate_ucb_score(self, candidate: Dict[str, Any]) -> Tuple[float, float, float]:
        """
        Calculate LinUCB upper confidence bound score for a single candidate.
        Returns: (total_ucb_score, expected_payoff, exploration_bonus)
        """
        x = self.extract_features(candidate)
        try:
            # Theta = A^(-1) * b
            A_inv = np.linalg.pinv(self.A)
            theta = np.dot(A_inv, self.b)

            # Expected payoff: x^T * theta
            expected_payoff = float(np.dot(x.T, theta)[0, 0])

            # Exploration variance: sqrt(x^T * A^(-1) * x)
            var = float(np.dot(np.dot(x.T, A_inv), x)[0, 0])
            variance_bonus = self.alpha * np.sqrt(max(0.0, var))

            total_score = expected_payoff + variance_bonus
            return total_score, expected_payoff, variance_bonus
        except Exception as exc:
            logger.warning("LinUCB calculation error: %s; using heuristic fallback", exc)
            fallback = float(candidate.get("score") or candidate.get("confidence") or 50.0) / 100.0
            return fallback, fallback, 0.0

    def rank_candidates(self, candidates: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
        """
        Rank candidate list using LinUCB scores and annotate each candidate.
        Guaranteed to never fail or return empty if candidates exist.
        """
        if not candidates:
            return []

        scored_candidates = []
        for cand in candidates:
            ucb, payoff, bonus = self.calculate_ucb_score(cand)
            cand_copy = dict(cand)
            cand_copy["bandit_ucb_score"] = round(ucb, 4)
            cand_copy["bandit_payoff"] = round(payoff, 4)
            cand_copy["bandit_bonus"] = round(bonus, 4)
            scored_candidates.append(cand_copy)

        # Sort descending by bandit UCB score
        scored_candidates.sort(key=lambda c: c.get("bandit_ucb_score", 0), reverse=True)

        for rank, cand in enumerate(scored_candidates, start=1):
            cand["bandit_rank"] = rank

        logger.info(
            "Contextual Bandit ranked %d candidates. Top pick: %s (UCB=%.3f, Payoff=%.3f, Bonus=%.3f)",
            len(scored_candidates),
            scored_candidates[0].get("symbol"),
            scored_candidates[0].get("bandit_ucb_score", 0),
            scored_candidates[0].get("bandit_payoff", 0),
            scored_candidates[0].get("bandit_bonus", 0),
        )

        return scored_candidates[:top_n]

    def update_with_reward(self, candidate: Dict[str, Any], reward: float) -> None:
        """
        Update covariance matrix A and vector b with realized EOD reward.
        A <- A + x * x^T
        b <- b + r * x
        """
        x = self.extract_features(candidate)
        try:
            r = float(np.clip(reward, -3.0, 3.0))
            self.A += np.dot(x, x.T)
            self.b += r * x
            self.total_pulls += 1
            self.total_rewards += r
        except Exception as exc:
            logger.error("Error updating bandit weights: %s", exc)


# ── Global Singleton & Public Helper Functions ─────────────────────────────────

_BANDIT_INSTANCE: ContextualBandit | None = None


def get_bandit() -> ContextualBandit:
    global _BANDIT_INSTANCE
    if _BANDIT_INSTANCE is None:
        try:
            from config import BANDIT_ALPHA, BANDIT_WEIGHTS_FILE
            alpha = BANDIT_ALPHA
            weights_file = BANDIT_WEIGHTS_FILE
        except Exception:
            alpha = 0.25
            weights_file = "data/bandit_weights.json"
        _BANDIT_INSTANCE = ContextualBandit(alpha=alpha, weights_path=weights_file)
    return _BANDIT_INSTANCE


def rank_candidates_with_bandit(candidates: List[Dict[str, Any]], top_n: int = 5) -> List[Dict[str, Any]]:
    """
    Public entry point for ranking morning candidates.
    Respects BANDIT_SELECTOR_ENABLED; falls back safely to original candidate list on error.
    """
    try:
        from config import BANDIT_SELECTOR_ENABLED
        if not BANDIT_SELECTOR_ENABLED:
            logger.info("Bandit selector disabled via config; using standard order")
            return candidates[:top_n]
    except Exception:
        pass

    try:
        bandit = get_bandit()
        return bandit.rank_candidates(candidates, top_n=top_n)
    except Exception as exc:
        logger.error("Bandit ranking failed: %s; falling back to original candidates", exc)
        return candidates[:top_n]


def update_bandit_eod(picks_with_results: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    After-market EOD training step. Called at 15:45 to update bandit matrices from
    realized outcomes (TP hits vs SL hits).
    """
    if not picks_with_results:
        return {"updated": 0, "status": "no_picks"}

    bandit = get_bandit()
    updated_count = 0

    for pick in picks_with_results:
        try:
            status = str(pick.get("status") or "").lower()
            ret = float(pick.get("result_return") or pick.get("return_pct") or 0.0)

            # Reward formulation:
            # TP hit: +1.0 base + positive return bonus
            # SL hit: -1.0 base - downside penalty
            # EOD close: return proportional reward
            if status == "tp_hit":
                reward = 1.0 + max(0.0, ret / 5.0)
            elif status == "sl_hit":
                reward = -1.2 - abs(ret / 5.0)
            else:
                reward = ret / 4.0

            bandit.update_with_reward(pick, reward)
            updated_count += 1
        except Exception as exc:
            logger.debug("Failed to process pick outcome for bandit: %s", exc)

    import datetime
    bandit.last_updated = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    bandit.save()

    logger.info("EOD Bandit learning complete. Updated %d picks. Total pulls: %d", updated_count, bandit.total_pulls)
    return {
        "updated": updated_count,
        "total_pulls": bandit.total_pulls,
        "avg_reward": round(bandit.total_rewards / max(1, bandit.total_pulls), 4),
        "last_updated": bandit.last_updated,
    }


def get_bandit_status() -> Dict[str, Any]:
    """Status dictionary for dashboard / health diagnostics."""
    bandit = get_bandit()
    return {
        "enabled": True,
        "total_pulls": bandit.total_pulls,
        "total_rewards": round(bandit.total_rewards, 4),
        "last_updated": bandit.last_updated or "Initial Prior",
        "alpha": bandit.alpha,
        "dim": bandit.dim,
    }
