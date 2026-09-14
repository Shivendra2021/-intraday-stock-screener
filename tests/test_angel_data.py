"""Offline contract tests for the read-only Angel One market-data adapter."""
from types import SimpleNamespace

import pandas as pd

from modules import angel_data
from modules.angel_data import AngelDataProvider
from modules.quant_store import Store


class Response:
    def __init__(self, status_code=200, payload=None):
        self.status_code = status_code
        self._payload = payload or {}

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(self.status_code)


def configured(monkeypatch, tmp_path):
    import config
    monkeypatch.setattr(config, "QUANT_DB_PATH", str(tmp_path / "quant.db"))
    monkeypatch.setattr(config, "ANGEL_ENABLED", True)
    monkeypatch.setattr(config, "ANGEL_API_KEY", "api-secret")
    monkeypatch.setattr(config, "ANGEL_CLIENT_CODE", "client-secret")
    monkeypatch.setattr(config, "ANGEL_PIN", "pin-secret")
    monkeypatch.setattr(config, "ANGEL_TOTP_SECRET", "JBSWY3DPEHPK3PXP")
    angel_data._AUTH.clear()
    return Store()


def test_authentication_generates_totp_without_persisting_secrets(monkeypatch, tmp_path):
    store = configured(monkeypatch, tmp_path)
    session = SimpleNamespace(post=lambda *a, **kw: Response(payload={"status": True, "data": {"jwtToken": "jwt"}}))
    provider = AngelDataProvider(store, session)
    assert provider.authenticate()
    state = store.get("angel_health")
    assert state["status"] == "ready" and "secret" not in str(state).lower()


def test_auth_failure_reauthenticates_once(monkeypatch, tmp_path):
    store = configured(monkeypatch, tmp_path)
    responses = iter([
        Response(payload={"status": True, "data": {"jwtToken": "one"}}),
        Response(401, {"status": False}),
        Response(payload={"status": True, "data": {"jwtToken": "two"}}),
        Response(payload={"status": True, "data": {"fetched": []}}),
    ])
    session = SimpleNamespace(post=lambda *a, **kw: next(responses))
    provider = AngelDataProvider(store, session)
    assert provider._post("/quote", {})["status"] is True
    assert angel_data._AUTH["jwt"] == "two"


def test_full_quote_requires_depth_timestamp_and_circuit(monkeypatch, tmp_path):
    store = configured(monkeypatch, tmp_path)
    provider = AngelDataProvider(store, SimpleNamespace())
    monkeypatch.setattr(provider, "sync_instruments", lambda: {"TEST": {"token": "1", "trading_symbol": "TEST-EQ"}})
    good = {"token": "1", "ltp": 100, "upperCircuit": 120, "lowerCircuit": 80,
            "exchFeedTime": "2026-09-14 09:35:00", "depth": {"buy": [{"price": 99.9}], "sell": [{"price": 100.0}]}}
    monkeypatch.setattr(provider, "_post", lambda *a: {"data": {"fetched": [good]}})
    assert provider.quote("TEST")["series"] == "EQ"
    del good["upperCircuit"]
    assert provider.quote("TEST") is None
    assert store.get("angel_health")["status"] == "partial_response"


def test_historical_candles_are_parsed(monkeypatch, tmp_path):
    store = configured(monkeypatch, tmp_path)
    provider = AngelDataProvider(store, SimpleNamespace())
    monkeypatch.setattr(provider, "sync_instruments", lambda: {"TEST": {"token": "1"}})
    monkeypatch.setattr(provider, "_post", lambda *a: {"data": [["2026-09-14T09:15:00+05:30", 100, 101, 99, 100.5, 1000]]})
    frame = provider.candles("TEST", "5m", pd.Timestamp("2026-09-14"), pd.Timestamp("2026-09-14"))
    assert list(frame.columns) == ["open", "high", "low", "close", "volume"]
    assert len(frame) == 1
