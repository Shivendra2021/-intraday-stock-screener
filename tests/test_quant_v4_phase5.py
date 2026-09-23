import os
import tempfile
import time
import pytest
from modules.quant_store import Store
from modules.catalyst_engine import (
    ensure_catalyst_tables,
    classify_catalyst,
    record_catalyst_event,
    get_point_in_time_catalysts,
)


@pytest.fixture
def temp_store():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    store = Store(path)
    ensure_catalyst_tables(store)
    yield store
    if os.path.exists(path):
        os.remove(path)


def test_catalyst_classification():
    cat, hi = classify_catalyst("Company bags Rs 850 Crore defense order from MoD")
    assert cat == "order_win"
    assert hi is True

    cat, hi = classify_catalyst("Q3 Net Profit jumps 45% YoY with strong margin expansion")
    assert cat == "earnings"
    assert hi is True

    cat, hi = classify_catalyst("USFDA approves ANDA for blood pressure generic drug")
    assert cat == "regulatory"
    assert hi is True

    cat, hi = classify_catalyst("Stock trades higher in morning session")
    assert cat == "general"
    assert hi is False


def test_catalyst_recording_and_deduplication(temp_store):
    now = int(time.time())
    ev1 = record_catalyst_event(
        symbol="TATAMOTORS",
        headline="Tata Motors bags 500 EV bus contract",
        published_at=now - 3600,
        source="Economic Times",
        store=temp_store,
    )
    assert len(ev1) == 16

    # Re-inserting the exact same event should be idempotent
    ev2 = record_catalyst_event(
        symbol="TATAMOTORS",
        headline="Tata Motors bags 500 EV bus contract",
        published_at=now - 3600,
        source="Economic Times",
        store=temp_store,
    )
    assert ev1 == ev2


def test_point_in_time_isolation_no_future_leakage(temp_store):
    """
    CRITICAL QUANT TEST:
    A signal is evaluated at 09:30 AM (decision_ts).
    News A was published at 08:45 AM (valid).
    News B was published at 09:45 AM (future - post signal).
    The system MUST see News A and MUST NOT see News B.
    """
    decision_ts = 1710000000  # Fixed epoch 09:30 AM
    news_past_ts = decision_ts - 2700  # 08:45 AM (45 mins earlier)
    news_future_ts = decision_ts + 900  # 09:45 AM (15 mins later)

    # Record past news
    record_catalyst_event(
        symbol="BEL",
        headline="BEL bags Rs 1200 Cr radar contract from Navy",
        published_at=news_past_ts,
        source="BSE",
        store=temp_store,
    )

    # Record future news (e.g. ingested later in the day)
    record_catalyst_event(
        symbol="BEL",
        headline="BEL management guides 25% revenue growth in Q4",
        published_at=news_future_ts,
        source="CNBC",
        store=temp_store,
    )

    # Evaluate catalyst features at decision_ts
    features = get_point_in_time_catalysts(
        symbol="BEL",
        decision_ts=decision_ts,
        lookback_hours=24.0,
        store=temp_store,
    )

    assert features["news_exists_before_signal"] == 1
    assert features["minutes_since_news"] == 45.0
    assert features["order_win_flag"] == 1
    assert features["high_impact_flag"] == 1
    assert "radar contract" in features["latest_headline"]
    assert "management guides" not in features["latest_headline"]
    assert features["event_count"] == 1  # Only 1 past event, future event excluded!


def test_empty_catalyst_when_no_prior_news(temp_store):
    decision_ts = 1710000000
    features = get_point_in_time_catalysts(
        symbol="INFY",
        decision_ts=decision_ts,
        store=temp_store,
    )
    assert features["news_exists_before_signal"] == 0
    assert features["minutes_since_news"] == -1.0
    assert features["event_count"] == 0
    assert features["latest_headline"] == ""
