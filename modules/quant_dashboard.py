"""Read-only dashboard views. Network refreshes are bounded and off the request path."""
from __future__ import annotations
import datetime as dt
import json
import math
from pathlib import Path
import re
import sqlite3
import subprocess
import sys
import threading
import time

from modules.quant_store import Store
from modules.quant_time import now_ist

ROOT = Path(__file__).resolve().parents[1]
_refresh_lock = threading.Lock()
_last_refresh = 0.0


def saved(name):
    import config
    path = Path(config.DB_PATH).resolve().parent / (name + '.json')
    try:
        return json.loads(path.read_text(encoding='utf-8-sig'))
    except (OSError, ValueError):
        return {}


def finite(value):
    try:
        value = float(value)
        return value if math.isfinite(value) else None
    except (TypeError, ValueError):
        return None


def market_worker():
    import yfinance as yf
    instruments = {'^NSEI':'NIFTY 50', '^NSEBANK':'BANK NIFTY', '^BSESN':'SENSEX',
                   'INR=X':'USD / INR', 'BZ=F':'Brent futures', '^TNX':'US 10Y yield', '^VIX':'US VIX'}
    data = yf.download(list(instruments), period='5d', interval='1d', group_by='ticker',
                       progress=False, threads=4, timeout=8, auto_adjust=False)
    rows = []
    for symbol, name in instruments.items():
        try:
            frame = data[symbol].dropna(subset=['Close'])
            if len(frame) < 2: continue
            close, previous = float(frame.Close.iloc[-1]), float(frame.Close.iloc[-2])
            rows.append({'symbol':symbol,'name':name,'price':close,'change_pct':(close/previous-1)*100,
                         'date':str(frame.index[-1].date()),'source':'Yahoo daily candles',
                         'series':[float(x) for x in frame.Close.tail(5)]})
        except (KeyError, ValueError, ZeroDivisionError):
            continue
    if rows:
        Store().put('dashboard_market', {'fetched_at':now_ist().isoformat(),'instruments':rows})


def refresh_market():
    global _last_refresh
    if time.monotonic() - _last_refresh < 300 or not _refresh_lock.acquire(False): return
    _last_refresh = time.monotonic()
    def work():
        try:
            with Store().lease('dashboard_market', 60) as acquired:
                if acquired:
                    subprocess.run([sys.executable,'-B','-m','modules.quant_dashboard','--market'],
                                   cwd=ROOT, capture_output=True, timeout=40)
        except (OSError, subprocess.TimeoutExpired):
            pass
        finally:
            _refresh_lock.release()
    threading.Thread(target=work,daemon=True).start()


def context(store=None):
    import config
    store = store or Store()
    today = str(now_ist().date())
    with store.connect() as c:
        # Two latest daily candles per symbol; do not mix sessions in mover ranks.
        bars = c.execute("SELECT symbol,ts,close,volume FROM (SELECT symbol,ts,close,volume,ROW_NUMBER() OVER(PARTITION BY symbol ORDER BY ts DESC) AS n FROM bars WHERE interval='1d') WHERE n<=2 ORDER BY symbol,ts DESC").fetchall()
        models = [dict(r) for r in c.execute('SELECT id,created_at,promoted,value FROM models ORDER BY created_at DESC LIMIT 12')]
        rejection_rows = c.execute('SELECT reason,COUNT(*) AS count FROM observations WHERE date=? GROUP BY reason ORDER BY count DESC',(today,)).fetchall()
        recent = c.execute('SELECT symbol,date,setup,reason,provenance FROM observations ORDER BY ts DESC LIMIT 20').fetchall()
    with sqlite3.connect(config.DB_PATH) as c:
        c.row_factory = sqlite3.Row
        history = [dict(r) for r in c.execute('SELECT date,symbol,entry_price,sl_price,target_price,status,result_return,source_label,session_type FROM picks ORDER BY date DESC,id DESC LIMIT 500')]
        sectors = {r[0]:r[1] or 'Unknown' for r in c.execute('SELECT symbol,sector FROM stock_universe')}
        patterns = [dict(r) for r in c.execute('SELECT pattern_key,success_rate,sample_count,last_market_update FROM patterns ORDER BY sample_count DESC LIMIT 20')]
    grouped = {}
    for r in bars: grouped.setdefault(r['symbol'],[]).append(r)
    movers = []
    for symbol, pair in grouped.items():
        if len(pair)==2 and pair[1]['close'] > 0:
            movers.append({'symbol':symbol,'price':pair[0]['close'],'change_pct':(pair[0]['close']/pair[1]['close']-1)*100,
                           'date':dt.datetime.fromtimestamp(pair[0]['ts'],dt.timezone.utc).astimezone(now_ist().tzinfo).date().isoformat(),
                           'sector':sectors.get(symbol,'Unknown')})
    date = max((r['date'] for r in movers),default=None)
    movers = sorted([r for r in movers if r['date']==date],key=lambda r:r['change_pct'],reverse=True)
    sector_rows = {}
    for r in movers:
        if r['sector'] != 'Unknown': sector_rows.setdefault(r['sector'],[]).append(r['change_pct'])
    news = saved('news_cache')
    articles = [{k:r.get(k) for k in ('title','desc','source','published','url','link')} for r in news.get('items',[])[:30]]
    macro = []
    for key, record in saved('fred_cache').items():
        if isinstance(record,dict):
            d = record.get('data',{})
            macro.append({'name':key,'value':finite(d.get('value')),'date':d.get('date'),'source':'FRED recorded observation'})
    fx = saved('twelve_data_cache').get('USD/INR',{})
    if fx: macro.append({'name':'USD/INR','value':finite(fx.get('price')),'date':fx.get('cached_at'),'source':'Twelve Data cached quote'})
    legacy = []
    report_fields = {
        'grok_brain_state': ('last_model_used', 'last_ok', 'last_review_time'),
        'grok_dashboard_state': ('market_status', 'latest_picks_date'),
        'ollama_intraday_agent_state': ('status',),
        'intraday_pattern_agent_report': ('phase', 'scanned', 'total_universe'),
        'audit_rules': ('version',),
        'continuous_state': ('last_scan', 'start_time'),
        'market_regime': ('regime', 'tracker_bias', 'nifty_change_pct', 'smallcap_change_pct', 'midcap_change_pct'),
    }
    for filename, label in [('grok_brain_state','AI brain'),('grok_dashboard_state','AI dashboard research'),
                            ('ollama_intraday_agent_state','Ollama research'),('intraday_pattern_agent_report','Pattern scanner'),
                            ('audit_rules','Risk auditor'),('continuous_state','Continuous learning'),('market_regime','Market regime')]:
        record = saved(filename)
        details = {k: record[k] for k in report_fields[filename]
                   if k in record and isinstance(record[k], (str, int, float, bool))}
        for key in ('insights', 'learned_patterns', 'penalty_rules', 'alert_log', 'setup_stats', 'watchlist'):
            if isinstance(record.get(key), (list, dict)):
                details[key + '_records'] = len(record[key])
        legacy.append({'name':label,'available':bool(record),'updated_at':record.get('updated_at') or record.get('last_updated') or record.get('date'),
                       'details':details,
                       'note':record.get('regime') if filename=='market_regime' else 'Recorded legacy research; not the Quant V3 decision engine'})
    for m in models:
        value=json.loads(m.pop('value')); m['evaluation']=value.get('evaluation',{}); m['trained_through']=value.get('trained_through'); m['evaluated_through']=value.get('evaluated_through')
    signals=store.signals()
    with store.connect() as c:
        for s in signals:
            r=c.execute('SELECT value FROM outcomes WHERE observation_id=?',(s['id'],)).fetchone()
            s['outcome']=json.loads(r[0]) if r else None
    usage=saved('api_usage_stats').get(today,{})
    try:
        from modules.grok_brain import get_brain_status
        ai_reviewers = get_brain_status()
    except Exception:
        ai_reviewers = {"enabled": False, "qwen_configured": False, "gemma_configured": False}
    return {'date':today,'market':store.get('dashboard_market',{}),'movers_date':date,
            'gainers':[r for r in movers if r['change_pct']>0][:10], 'losers':sorted([r for r in movers if r['change_pct']<0],key=lambda r:r['change_pct'])[:10],
            'sectors':[{'name':s,'change_pct':sum(v)/len(v),'samples':len(v)} for s,v in sector_rows.items()],
            'mover_coverage':len(movers),'unknown_sector_count':sum(r['sector']=='Unknown' for r in movers),
            'news':articles,'news_cached_at':news.get('timestamp'),'macro':macro,'legacy':legacy,'patterns':patterns,
            'models':models,'history':history,'signals':signals[-500:],'rejections':[dict(r) for r in rejection_rows],
            'activity':[dict(r) for r in recent],'usage':[{'name':k,'calls':v if isinstance(v,(int,float)) else None} for k,v in usage.items()],
            'configuration':{'Angel':bool(config.ANGEL_ENABLED and config.ANGEL_API_KEY and config.ANGEL_CLIENT_CODE
                                          and config.ANGEL_PIN and config.ANGEL_TOTP_SECRET),
                             'Dhan optional':bool(config.DHAN_CLIENT_ID and config.DHAN_ACCESS_TOKEN),
                             'Telegram':bool(config.TELEGRAM_BOT_TOKEN and config.TELEGRAM_CHAT_ID)},
            'ai_reviewers':ai_reviewers,
            'angel': store.get('angel_health', {'status':'not_configured'}),
            'backfill': store.get('backfill', {}),
            'quant_qualitative_review': store.get('quant_ai_review', {}),
            'benchmark':store.get('benchmark',{}),'preparation':store.get('preparation',{})}


def stock_detail(symbol, store=None):
    if not re.fullmatch(r'[A-Z0-9&._-]{1,35}',symbol): raise ValueError('Invalid symbol')
    store=store or Store()
    with store.connect() as c:
        bars=[dict(r) for r in c.execute("SELECT ts,open,high,low,close,volume,source FROM bars WHERE symbol=? AND interval='5m' ORDER BY ts DESC LIMIT 150",(symbol,))][::-1]
        rows=c.execute('SELECT features,reason,provenance,date FROM observations WHERE symbol=? ORDER BY ts DESC LIMIT 1',(symbol,)).fetchall()
        outcomes=c.execute('SELECT t.value FROM outcomes t JOIN observations o ON o.id=t.observation_id WHERE o.symbol=? AND t.resolved=1',(symbol,)).fetchall()
    observation={**dict(rows[0]),'features':json.loads(rows[0]['features'])} if rows else None
    if bars:
        last_date=dt.datetime.fromtimestamp(bars[-1]['ts'],now_ist().tzinfo).date()
        bars=[r for r in bars if dt.datetime.fromtimestamp(r['ts'],now_ist().tzinfo).date()==last_date]
    filled=[json.loads(r[0]) for r in outcomes if json.loads(r[0]).get('return_pct') is not None]
    return {'symbol':symbol,'bars':bars,'observation':observation,'signals':[r for r in store.signals() if r['symbol']==symbol][-5:],
            'research':{'samples':len(filled),'hit7':sum(r.get('hit7',0) for r in filled),'hit10':sum(r.get('hit10',0) for r in filled)},
            'catalyst':saved('catalyst_cache').get(symbol,{}).get('data')}


if __name__=='__main__' and '--market' in sys.argv:
    market_worker()
