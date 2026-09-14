"""Unit tests must not alter a running screener or contact external services."""
import sys
import pytest


def pytest_addoption(parser):
    parser.addoption("--run-market-integration", action="store_true", default=False,
                     help="Run the legacy scanner subprocess tests that require real market data")


def pytest_collection_modifyitems(config, items):
    if not config.getoption("--run-market-integration"):
        for item in items:
            if item.path.name == "test_intraday_pattern_scan.py":
                item.add_marker(pytest.mark.skip(reason="Market-data integration: opt in with --run-market-integration"))


@pytest.fixture(scope="session", autouse=True)
def session_workspace(tmp_path_factory):
    import os
    from pathlib import Path
    root = str(Path(__file__).resolve().parents[1])
    patch = pytest.MonkeyPatch()
    path = tmp_path_factory.mktemp("runtime")
    patch.chdir(path)
    patch.setenv("PYTHONPATH", root + os.pathsep + os.environ.get("PYTHONPATH", ""))
    yield path
    patch.undo()


@pytest.fixture(autouse=True)
def isolated_runtime(tmp_path, monkeypatch, session_workspace):
    import config
    import requests
    import pandas as pd
    import yfinance
    old_db = config.DB_PATH
    monkeypatch.chdir(session_workspace)
    (session_workspace / "data").mkdir(exist_ok=True)
    (session_workspace / "logs").mkdir(exist_ok=True)
    (tmp_path / "data").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)
    test_db = str(tmp_path / "data" / "history.db")
    monkeypatch.setattr(config, "DB_PATH", test_db)
    monkeypatch.setattr(config, "QUANT_DB_PATH", str(tmp_path / "data" / "quant.db"))
    # Modules importing DB_PATH at collection time must use the same isolated DB.
    for name, module in list(sys.modules.items()):
        if name.startswith(("modules.", "dashboard.", "app.")) and getattr(module, "DB_PATH", None) == old_db:
            monkeypatch.setattr(module, "DB_PATH", test_db)
    def blocked(*args, **kwargs):
        raise requests.ConnectionError("External requests are disabled in unit tests")
    monkeypatch.setattr(requests.adapters.HTTPAdapter, "send", blocked)
    monkeypatch.setattr(yfinance, "download", lambda *a, **kw: pd.DataFrame())
    monkeypatch.setattr(yfinance.Ticker, "history", lambda *a, **kw: pd.DataFrame())
    try:
        import curl_cffi.requests
        monkeypatch.setattr(curl_cffi.requests.Session, "request", blocked)
    except ImportError:
        pass
    from modules.db_migrations import ensure_research_tables
    ensure_research_tables()
