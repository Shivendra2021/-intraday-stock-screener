"""Offline regression tests for the quant selection and paper accounting contract."""
import datetime as dt
import json
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from modules.quant_store import Store, dumps
from modules.quant_features import build_features, quote_gate, VERSION, FEATURES
from modules.quant_outcomes import evaluate
from modules.quant_learning import active_model, portfolio, metrics, train


@pytest.fixture
def store(tmp_path, monkeypatch):
    import config
    monkeypatch.setattr(config, "QUANT_DB_PATH", str(tmp_path / "quant.db"))
    monkeypatch.setattr(config, "DB_PATH", str(tmp_path / "history.db"))
    monkeypatch.setattr(config, "DRY_RUN", True)
    return Store()


def candles(start, values):
    return pd.DataFrame(values, columns=["open", "high", "low", "close", "volume"],
                        index=pd.date_range(start, periods=len(values), freq="5min", tz="Asia/Kolkata"))


def signal():
    return {"symbol": "TEST", "date": "2026-08-31", "ts": int(pd.Timestamp("2026-08-31 09:35", tz="Asia/Kolkata").timestamp()),
            "price": 100, "stop": 98, "cost_bps": 20, "slippage_bps": 0, "setup": "opening_expansion"}


def test_partial_exits_are_weighted_and_costed():
    bars = candles("2026-08-31 09:40", [[100, 107.5, 99, 107, 1000], [107, 111, 106, 110, 1000]])
    out = evaluate(signal(), bars)
    assert out["status"] == "target_exit"
    assert out["return_pct"] == pytest.approx(8.3)
    assert [f["fraction"] for f in out["fills"]] == [.5, .5]
    assert out["hit7"] == out["hit10"] == 1


def test_ambiguous_stop_target_bar_is_loss():
    out = evaluate(signal(), candles("2026-08-31 09:40", [[100, 111, 97, 110, 1000]]))
    assert out["return_pct"] == pytest.approx(-2.2)
    assert out["hit7"] == 0


def test_target_then_runner_stop_and_gap_accounting():
    bars = candles("2026-08-31 09:40", [[100, 108, 99, 107, 1000], [102, 104, 101, 103, 1000]])
    out = evaluate(signal(), bars)
    assert out["return_pct"] == pytest.approx(4.3)
    assert out["hit7"] == 1 and out["hit10"] == 0


def test_signal_bar_and_processing_interval_are_excluded():
    bars = candles("2026-08-31 09:30", [[100, 120, 90, 100, 1000], [100, 120, 90, 100, 1000], [100, 101, 97, 98, 1000]])
    assert evaluate(signal(), bars)["return_pct"] == pytest.approx(-2.2)


@pytest.mark.parametrize("kind", ["entry", "gap", "zero_volume", "empty", "unfinished"])
def test_incomplete_data_never_becomes_zero_return(kind):
    bars = candles("2026-08-31 09:40", [[100, 101, 99, 100, 1000]] * 3)
    if kind == "entry": bars = bars.iloc[1:]
    if kind == "gap": bars = bars.drop(bars.index[1])
    if kind == "zero_volume": bars.iloc[1, 4] = 0
    if kind == "empty": bars = bars.iloc[:0]
    result = evaluate(signal(), bars)
    assert result["resolved"] is False
    assert result["return_pct"] is None


def test_gap_cancels_entry_instead_of_improving_backtest():
    out = evaluate(signal(), candles("2026-08-31 09:40", [[105, 120, 104, 119, 1000]]))
    assert out["resolved"] and out["status"] == "unfilled"
    assert out["return_pct"] is None


def test_eod_requires_last_complete_bar():
    bars = candles("2026-08-31 09:40", [[100, 101, 99, 100.5, 1000]] * 68)
    assert evaluate(signal(), bars)["return_pct"] == pytest.approx(.3)
    assert evaluate(signal(), bars.iloc[:-1])["return_pct"] is None


def test_features_do_not_see_future_or_todays_daily_bar():
    daily = pd.DataFrame({"open":100., "high":102., "low":98., "close":100., "volume":1e6},
                         index=pd.date_range("2026-06-01", "2026-08-31", freq="B", tz="Asia/Kolkata"))
    bars = pd.concat([candles(f"{date} 09:15", [[100,101,99,100,1000]]*6)
                      for date in ["2026-08-24","2026-08-25","2026-08-26","2026-08-27","2026-08-28","2026-08-31"]])
    asof = pd.Timestamp("2026-08-31 09:35", tz="Asia/Kolkata")
    first = build_features("TEST", daily, bars, asof)
    assert first is not None and first["rvol"] == 1
    daily.loc[daily.index[-1], "close"] = 10000
    bars.loc[bars.index >= asof, ["high", "close", "volume"]] = 10000
    assert build_features("TEST", daily, bars, asof) == first
    assert build_features("TEST", daily, bars.drop(bars.index[-5]), asof) is None


@pytest.mark.parametrize("change,expected", [({"ts":1},"quote_stale"), ({"series":None},"series_not_verified"),
    ({"upper":105},"insufficient_price_band_headroom"), ({"bid":99},"spread_too_wide"), ({"ask":None},"spread_or_price_band_unavailable")])
def test_quote_gates_fail_closed(change, expected):
    now = pd.Timestamp("2026-08-31 09:35", tz="Asia/Kolkata")
    quote = {"ts":now.timestamp(), "series":"EQ", "bid":99.95, "ask":100, "upper":120}
    assert quote_gate(signal(), quote, now) == "eligible"
    assert quote_gate(signal(), {**quote, **change}, now) == expected


def test_store_immutable_outcomes_and_three_slot_cap(store):
    ids = []
    for i in range(5):
        row = {**signal(), "symbol":f"TEST{i}"}
        ident = store.observe(row, "eligible")
        ids.append(ident)
        assert store.add_signal(ident, row) == (i < 3)
    assert not store.add_signal(ids[0], signal())
    store.outcome(ids[0], {"resolved":False})
    store.outcome(ids[0], {"resolved":True, "return_pct":-2})
    store.outcome(ids[0], {"resolved":True, "return_pct":10})
    with store.connect() as c:
        assert json.loads(c.execute("SELECT value FROM outcomes WHERE observation_id=?",(ids[0],)).fetchone()[0])["return_pct"] == -2
    with store.lease("test") as acquired:
        assert acquired
        with store.lease("test") as second: assert not second
    with store.lease("test") as third: assert third


def test_future_model_never_activates(store):
    import config
    model = {"id":"x", "feature_version":VERSION, "evaluated_through":"2026-08-31",
             "cost_bps":config.QUANT_COST_BPS,"slippage_bps":config.QUANT_SLIPPAGE_BPS}
    with store.connect() as c: c.execute("INSERT INTO models VALUES (?,?,?,?)",("x",1,dumps(model),1))
    assert active_model(store,"2026-08-31") is None
    assert active_model(store,"2026-09-01")["id"] == "x"
    assert active_model(store,"2026-11-01") is None


def test_portfolio_keeps_unfilled_slots_and_uses_chronology():
    rows = [{**signal(), "symbol":f"T{i}", "sector":"Unknown", "p7":.5+i*.01,
             "expected_net_pct":1, "ts":signal()["ts"]+i*300,
             "outcome":{"return_pct":None if i==0 else 2, "hit7":0,"hit10":0}}
            for i in range(5)]
    picks = portfolio(rows)
    assert [r["symbol"] for r in picks] == ["T0","T1","T2"]
    assert metrics(picks)["signals"] == 3 and metrics(picks)["trades"] == 2


def test_no_training_evidence_means_no_model(store):
    result = train(store)
    assert result["status"] == "backfilling"
    assert result["remaining_sessions"] > 0
    assert active_model(store,"2026-09-01") is None


def test_historical_success_cannot_promote_without_forward_records(store, monkeypatch):
    import modules.quant_learning as learning
    rows = []
    for date in pd.bdate_range("2026-06-01", periods=30):
        for i in range(12):
            win = i % 2
            row = {**signal(), **dict.fromkeys(FEATURES, 1.), "symbol":f"T{i}", "date":str(date.date()),
                   "ts":int(date.tz_localize('Asia/Kolkata').timestamp()) + 34500,
                   "rvol":2+win, "baseline_score":70, "sector":"Unknown", "recording_provenance":"historical_current_universe",
                   "outcome":{"return_pct":8.3 if win else -2.2, "hit7":win, "hit10":win, "fills":[]}}
            rows.append(row)
    monkeypatch.setattr(learning,"training_rows",lambda _:rows)
    result = train(store)
    assert result["status"] == "insufficient_forward_evidence"
    assert result["forward_evidence_ready"] is False
    assert result["forward_recorded"]["trades"] == 0
    assert active_model(store,"2026-08-01") is None


def test_missing_previous_session_is_not_valid_daily_history():
    from modules.quant_features import daily_features
    frame = pd.DataFrame({"open":100.,"high":102.,"low":98.,"close":100.,"volume":1e6},
                         index=pd.bdate_range("2026-06-01","2026-08-28",tz="Asia/Kolkata"))
    assert daily_features(frame,dt.date(2026,8,31)) is not None
    assert daily_features(frame.iloc[:-1],dt.date(2026,8,31)) is None


def test_download_cache_and_timeout_preserve_data(store, monkeypatch):
    from modules.quant_data import DataService
    import subprocess
    calls = []
    def download(*args, **kwargs):
        calls.append(kwargs)
        return SimpleNamespace(returncode=0, stdout='{"updated":["TEST"]}')
    monkeypatch.setattr(subprocess,"run",download)
    service = DataService(store)
    assert service.refresh(["TEST"])["updated"] == 1
    assert service.refresh(["TEST"])["cache_hits"] == 1
    assert len(calls) == 1 and calls[0]["timeout"] <= 45
    store.save_bars("OTHER","5m",candles("2026-08-31 09:40",[[100,101,99,100,1000]]),"test")
    def timeout(*a, **kw): raise subprocess.TimeoutExpired("test",1)
    monkeypatch.setattr(subprocess,"run",timeout)
    assert service.refresh(["OTHER"])["failed"] == 1
    assert len(store.bars("OTHER","5m")) == 1


def test_cycle_never_fills_without_model(store, monkeypatch):
    import modules.quant_engine as engine
    now = pd.Timestamp("2026-08-31 09:35",tz="Asia/Kolkata")
    store.put("watchlist",{"date":str(now.date()), "candidates":[]})
    monkeypatch.setattr(engine,"universe",lambda:{})
    result = engine.cycle(store, now=now, refresh=False)
    assert result["status"] == "backfilling"
    assert store.signals() == []


@pytest.mark.parametrize("quote_available,expected", [(True,3),(False,0)])
def test_confirmed_cycle_and_restart_are_idempotent(store, monkeypatch, quote_available, expected):
    import modules.quant_engine as engine
    now = pd.Timestamp("2026-08-31 09:35:10",tz="Asia/Kolkata")
    symbols = {f"T{i}":f"Sector{i}" for i in range(5)}
    store.put("watchlist",{"date":str(now.date()), "candidates":[{"symbol":s} for s in symbols]})
    store.put("daily_features",{"date":str(now.date()), "symbols":{s:{"sector":sec} for s,sec in symbols.items()}})
    monkeypatch.setattr(engine,"universe",lambda:symbols)
    monkeypatch.setattr(engine,"active_model",lambda *args:{"id":"test"})
    monkeypatch.setattr(engine,"build_features",lambda sym,*a:{**signal(), **dict.fromkeys(FEATURES,1.),
                        "feature_version":VERSION, "symbol":sym, "sector":symbols[sym], "rvol":2,
                        "turnover":3e7, "baseline_score":80})
    monkeypatch.setattr(engine,"predict",lambda model,rows:[{**r,"p7":.6,"p10":.3,"expected_net_pct":2,"model_id":"test"} for r in rows])
    class Feed:
        def quote(self, symbol):
            return {"ts":now.timestamp(),"bid":99.95,"ask":100,"upper":120,"series":"EQ"} if quote_available else None
    engine.cycle(store,service=Feed(),now=now,refresh=False)
    engine.cycle(store,service=Feed(),now=now,refresh=False)
    assert len(store.signals()) == expected
    import sqlite3, config
    with sqlite3.connect(config.DB_PATH) as c:
        assert c.execute("SELECT COUNT(*) FROM picks WHERE source_label LIKE 'quant_v3:%'").fetchone()[0] == expected
        if expected:
            session, official = c.execute("SELECT session_type,is_official_morning FROM picks WHERE source_label LIKE 'quant_v3:%' LIMIT 1").fetchone()
            assert session == "quant_v3_intraday" and official == 0


def test_runtime_lock_and_nontrading_day(store):
    from modules.quant_runtime import run_once
    with store.lease("runtime"):
        assert run_once(now=pd.Timestamp("2026-08-30 10:00",tz="Asia/Kolkata"))["status"] == "busy"
    assert run_once(now=pd.Timestamp("2026-08-30 10:00",tz="Asia/Kolkata"))["status"] == "non_trading_day"


def test_dashboard_no_fake_metrics_and_controls(store, monkeypatch):
    from dashboard import app as dashboard
    import config
    monkeypatch.setattr(dashboard,"DB_PATH",config.DB_PATH)
    client = dashboard.app.test_client()
    assert client.get("/api/quant").status_code == 200
    assert client.get("/api/quant").json["signals"] == []
    p = {}
    dashboard._quant_indicators(p)
    assert p["rvol"] is p["adr_exp"] is p["clv"] is None
    assert client.get("/api/system/toggle").status_code == 405
    assert client.post("/api/system/toggle",headers={"Origin":"https://untrusted.example"}).status_code == 403
