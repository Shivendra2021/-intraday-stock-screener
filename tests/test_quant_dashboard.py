import json
import sqlite3
import pandas as pd
import pytest
from modules.quant_store import Store
from modules.quant_dashboard import context, stock_detail


def test_dashboard_empty_state_is_not_fabricated():
    data=context()
    assert data['gainers']==data['losers']==data['models']==[]
    assert data['market']=={}
    assert 'ai_reviewers' in data
    assert len(data['legacy'])==7
    assert not any(r['available'] for r in data['legacy'])


def test_movers_do_not_mix_dates_or_include_flat_as_losers():
    store=Store()
    def save(symbol,dates,prices):
        frame=pd.DataFrame({'open':prices,'high':prices,'low':prices,'close':prices,'volume':1000},index=pd.to_datetime(dates).tz_localize('Asia/Kolkata'))
        store.save_bars(symbol,'1d',frame,'test')
    save('UP',['2026-08-27','2026-08-28'],[100,110])
    save('DOWN',['2026-08-27','2026-08-28'],[100,90])
    save('OLD',['2026-08-26','2026-08-27'],[100,150])
    save('FLAT',['2026-08-27','2026-08-28'],[100,100])
    data=context(store)
    assert [r['symbol'] for r in data['gainers']]==['UP']
    assert [r['symbol'] for r in data['losers']]==['DOWN']
    assert data['movers_date']=='2026-08-28'


def test_news_retains_original_date_and_history_engine(tmp_path):
    import config
    from pathlib import Path
    path=Path(config.DB_PATH).parent/'news_cache.json'
    path.write_text(json.dumps({'items':[{'title':'Old report','published':'2023-01-01','source':'Example','api_key':'must not appear'}]}))
    with sqlite3.connect(config.DB_PATH) as c:
        c.execute("INSERT INTO picks(date,symbol,status,source_label) VALUES ('2026-08-28','TEST','pending','legacy')")
    data=context()
    assert data['news'][0]['published']=='2023-01-01'
    assert 'api_key' not in data['news'][0]
    assert data['history'][0]['source_label']=='legacy'
    assert data['signals']==[]


def test_stock_detail_rejects_path_and_only_returns_last_session():
    store=Store()
    dates=pd.to_datetime(['2026-08-27 09:15','2026-08-28 09:15']).tz_localize('Asia/Kolkata')
    frame=pd.DataFrame({'open':100,'high':101,'low':99,'close':100,'volume':1000},index=dates)
    store.save_bars('TEST','5m',frame,'test')
    assert len(stock_detail('TEST',store)['bars'])==1
    with pytest.raises(ValueError):stock_detail('../config',store)


def test_workspace_routes_and_template(monkeypatch):
    import modules.quant_dashboard as view
    from dashboard.app import app
    monkeypatch.setattr(view,'refresh_market',lambda:None)
    client=app.test_client()
    assert client.get('/api/quant/workspace').status_code==200
    assert client.get('/api/quant/stock/TEST').json['bars']==[]
    assert client.get('/api/quant/stock/invalid!').status_code==400
    page=client.get('/').text
    for name in ['markets','watchlist','tracking','performance','learning','system']:
        assert f'data-view="{name}"' in page
    assert client.get('/legacy').status_code==200


def test_dashboard_status_routes_never_trigger_slow_refresh(monkeypatch):
    from dashboard.app import app
    import modules.ollama_intraday_agent as ollama
    import modules.twelve_data_provider as twelve
    monkeypatch.setattr(ollama, '_load_state', lambda: {'status': 'saved'})
    monkeypatch.setattr(twelve, 'get_usdinr_rate', lambda: pytest.fail('request path fetched Twelve Data'))
    client=app.test_client()
    assert client.get('/api/ollama-agent').json['status']=='saved'
    macro=client.get('/api/macro-pulse').json
    assert 'usdinr' in macro and 'fred' in macro
    assert client.get('/').status_code==200
    assert 'old-theme.css' in client.get('/').text
