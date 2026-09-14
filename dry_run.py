"""Offline Quant V3 lifecycle verification. It never contacts a provider or Telegram."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pandas as pd

from modules.quant_features import quote_gate
from modules.quant_review import review
from modules.quant_store import Store


def main():
    now = pd.Timestamp("2026-08-31 09:35", tz="Asia/Kolkata")
    row = {"symbol": "FIXTURE", "date": str(now.date()), "ts": int(now.timestamp()),
           "entry_ts": int(now.timestamp()) + 300, "price": 100.0, "stop": 98.0,
           "sector": "Fixture", "p7": .42, "p10": .18, "expected_net_pct": 1.3,
           "model_id": "fixture-model", "feature_version": "fixture"}
    quote = {"ts": now.timestamp(), "series": "EQ", "bid": 99.95, "ask": 100.0, "upper": 120.0}
    with tempfile.TemporaryDirectory() as folder:
        store = Store(str(Path(folder) / "quant.db"))
        ident = store.observe(row, "eligible")
        passed = review(row, model_ready=True, quote_reason=quote_gate(row, quote, now), in_window=True)
        store.record_review(ident, row, passed["decision"], passed)
        assert passed["decision"] == "qualified"
        assert store.add_signal(ident, {**row, "quote": quote, "upper": quote["upper"]})
        stale = review(row, model_ready=True, quote_reason=quote_gate(row, {**quote, "ts": 1}, now), in_window=True)
        assert stale["decision"] == "rejected"
        before = review(row, model_ready=True, quote_reason="eligible", in_window=False)
        assert before["decision"] == "watchlist"
        output = {"status": "passed", "network_calls": 0, "telegram_calls": 0,
                  "qualified": len(store.signals()), "review_rows": len(store.reviews()),
                  "checks": ["valid quote qualifies", "stale quote rejects", "outside window watchlists"]}
    print(json.dumps(output, indent=2))


if __name__ == "__main__":
    main()

