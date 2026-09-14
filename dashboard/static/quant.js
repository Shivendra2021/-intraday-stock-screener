'use strict';
const el = id => document.getElementById(id);
const text = (id, value) => { el(id).textContent = value; };
const number = (v, digits = 2) => v == null ? 'Unavailable' : Number(v).toLocaleString('en-IN', {maximumFractionDigits: digits});
const human = v => (v || 'not evaluated').replaceAll('_', ' ');
let busy = false, enabled = false;
let quantState = null, workspaceState = null;
function cellRow(parent, values) {
  const tr = document.createElement('tr');
  for (const value of values) { const td = document.createElement('td'); td.textContent = value; tr.append(td); }
  parent.append(tr);
}
function definitions(id, pairs) {
  el(id).replaceChildren();
  for (const [label, value] of pairs) {
    const term = document.createElement('dt'), detail = document.createElement('dd');
    term.textContent = label; detail.textContent = value; el(id).append(term, detail);
  }
}
async function json(url, options) {
  const response = await fetch(url, {...options, signal: AbortSignal.timeout(10000)});
  if (!response.ok) throw new Error(`${url}: ${response.status}`);
  return response.json();
}
async function refresh() {
  if (busy) return;
  busy = true;
  try {
    const data = await json('/api/quant');
    quantState = data;
    const watch = data.watchlist || {}, learning = data.learning || {}, perf = data.performance || {}, audit = data.provider_audit || {};
    text('date', data.date); text('session', human(data.runtime.status)); text('pick-count', `${data.signals.length} / 3`);
    text('coverage', `${number(watch.coverage, 0)} / ${number(watch.universe_size, 0)}`);
    text('observations', number(data.observations, 0));
    text('returns', perf.mean_net_pct == null ? 'Not measured' : `${number(perf.mean_net_pct)}%`);
    text('fills', `${perf.filled_closed} closed modeled outcomes · ${perf.unfilled} unfilled`);
    text('watch-date', watch.date || 'Not prepared');
    text('watch-note', `Showing up to 20 of ${(watch.candidates || []).length} recorded candidates. Watchlist date is shown above.`);
    el('watch').replaceChildren();
    for (const r of (watch.candidates || []).slice(0, 8)) cellRow(el('watch'), [r.symbol, r.sector, number(r.atr_pct), number(r.turnover, 0)]);
    text('watch-note', `Showing 8 of ${(watch.candidates || []).length} candidates. Explore the full list in Watchlist.`);
    text('learning', human(learning.status));
    definitions('evidence', [['Historical sessions', learning.historical_sessions ?? learning.sessions ?? 0],
      ['Historical samples', learning.historical_samples ?? learning.samples ?? 0],
      ['Forward sessions', `${learning.forward_sessions ?? 0} / ${learning.required_forward_sessions ?? 5}`],
      ['Forward observations', `${learning.forward_eligible_observations ?? 0} / ${learning.required_forward_observations ?? 20}`],
      ['Remaining historical sessions', learning.remaining_sessions ?? 0], ['Remaining historical samples', learning.remaining_samples ?? 0],
      ['Active model', data.runtime.model_id || 'None'], ['Shadow model', data.runtime.shadow_model_id || 'None'],
      ['Forward evidence passed', learning.forward_evidence_ready ? 'Yes' : 'No'],
      ['+7% reach rate', perf.hit7_rate == null ? 'Not measured' : `${number(perf.hit7_rate * 100)}%`],
      ['+10% reach rate', perf.hit10_rate == null ? 'Not measured' : `${number(perf.hit10_rate * 100)}%`]]);
    definitions('feeds', [['Last candle refresh', data.data_health.checked_at || 'Not checked'],
      ['Dhan audit', human(audit.dhan?.status || 'not checked')], ['NSE quote audit', audit.nse ? (audit.nse.quote_available ? 'Available at audit' : 'Unavailable at audit') : 'Not checked'],
      ['Cycle duration', data.runtime.elapsed_seconds == null ? 'Not measured' : `${number(data.runtime.elapsed_seconds)} s`]]);
    el('slots').replaceChildren();
    for (let i = 0; i < 3; i++) {
      const slot = document.createElement('article'); slot.className = 'slot';
      const label = document.createElement('small'); label.textContent = `SLOT ${i + 1}`;
      const title = document.createElement('h3'), body = document.createElement('p');
      const signal = data.signals[i];
      if (signal) {
        const p = signal.value, out = signal.outcome;
        title.textContent = signal.symbol;
        const review=p.review||{};
        body.textContent = `Reference ₹${number(p.price)} · Stop ₹${number(p.stop)} · P(+7%): ${number(p.p7*100)}% · ${human(review.reason||'verified')} · ${human(out?.status || 'pending entry')}${out?.return_pct != null ? ' · Net '+number(out.return_pct)+'%' : ''}`;
      } else { title.textContent = 'No qualified candidate'; body.textContent = 'Waiting for evidence, fresh quote verification, and deterministic review gates.'; }
      slot.append(label, title, body); el('slots').append(slot);
    }
    el('watch-candidates').replaceChildren();
    const watchCandidates=data.runtime.watch_candidates||[];
    for(let i=0;i<3;i++){
      const card=document.createElement('article');card.className='slot';const item=watchCandidates[i];
      if(item){card.append(node('small',`WATCH ${i+1}`),node('h3',item.symbol),node('p',`Reference ₹${number(item.price)} · ${human(item.review?.reason||item.rejection)} · Not qualified for alert.`));}
      else{card.append(node('small',`WATCH ${i+1}`),node('h3','No watch candidate'),node('p','No weaker candidate is being promoted into a qualified slot.'));}
      el('watch-candidates').append(card);
    }
    text('connection', `Read at ${new Date().toLocaleTimeString('en-IN', {timeZone:'Asia/Kolkata'})} IST`);
    renderWatch(); renderSystem();
  } catch (error) { text('connection', 'Connection unavailable · displayed values may be stale'); }
  finally { busy = false; }
}
async function history() {
  if (workspaceState) { renderHistory(); return; }
  try {
    const data = await json('/api/history'); if (workspaceState) { renderHistory(); return; } el('history').replaceChildren();
    for (const r of data.picks.slice(0, 30)) cellRow(el('history'), [r.date, r.symbol, number(r.entry_price), human(r.status), number(r.result_return)]);
    if (!data.picks.length) cellRow(el('history'), ['No recorded history', '', '', '', '']);
  } catch (error) { el('history').replaceChildren(); cellRow(el('history'), ['History unavailable', '', '', '', '']); }
}
async function powerStatus() {
  try { const data = await json('/api/system/status'); enabled = Boolean(data.running ?? data.enabled); text('power', enabled ? 'Pause scheduler' : 'Start scheduler'); }
  catch (error) { text('power', 'Scheduler unavailable'); }
}
el('refresh').addEventListener('click', () => { refresh(); history(); powerStatus(); });
el('power').addEventListener('click', async () => {
  el('power').disabled = true;
  try { await json('/api/system/toggle', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({action:enabled ? 'off' : 'on'})}); await powerStatus(); }
  catch (error) { text('connection', 'Scheduler control failed'); }
  finally { el('power').disabled = false; }
});
// Explicit view routing keeps all saved panels available without mixing engines.
const pages = {overview:['Your market. In focus.','The session, the evidence, and your next decision.'], markets:['The broader picture.','Indices, covered-universe movers, macro observations, and sourced news.'], watchlist:['Follow the opportunity.','Research candidates are separate from qualified candidates.'], tracking:['Every outcome accounted for.','Resolved outcomes and remaining candidate states in one ledger.'], performance:['Measure what happened.','Quant V3 performance stays separate from legacy records.'], learning:['Evidence drives improvement.','Model evaluations, recorded patterns, and the research library.'], system:['Know what is working.','Data coverage, recorded usage, freshness, and scheduler health.']};
el('slots').closest('section').dataset.page = 'overview';
document.querySelector('main > .grid').dataset.page = 'overview';
el('watch').closest('.layout').dataset.page = 'overview';
el('history').closest('section').dataset.page = 'performance';
el('history').closest('section').before(el('performance-summary'));
function route(view) {
  if (!pages[view]) view = 'overview';
  document.querySelectorAll('[data-page]').forEach(node => { node.hidden = node.dataset.page !== view; });
  document.querySelectorAll('[data-view]').forEach(node => { if (node.dataset.view === view) node.setAttribute('aria-current','page'); else node.removeAttribute('aria-current'); });
  text('page-title',pages[view][0]); text('page-description',pages[view][1]);
}
document.querySelectorAll('[data-view]').forEach(button => button.addEventListener('click',()=>{location.hash=button.dataset.view; route(button.dataset.view);}));
window.addEventListener('hashchange',()=>route(location.hash.slice(1)));
route(location.hash.slice(1));
function node(tag, content, className) { const n=document.createElement(tag); if(content!=null)n.textContent=content; if(className)n.className=className; return n; }
function empty(id, message='No recorded data available.') { el(id).replaceChildren(node('p',message,'empty')); }
function stockButton(symbol) { const b=node('button',symbol,'symbol'); b.addEventListener('click',()=>openStock(symbol)); return b; }
function table(id, headers, rows) {
  el(id).replaceChildren();
  if(!rows.length){empty(id);return;}
  const t=node('table'), head=node('thead'), tr=node('tr'), body=node('tbody');
  headers.forEach(h=>tr.append(node('th',h)));head.append(tr);t.append(head,body);
  rows.forEach(values=>{const row=node('tr');values.forEach(value=>{const c=node('td');value instanceof Node?c.append(value):c.textContent=value;row.append(c);});body.append(row);});el(id).append(t);
}
function cards(id, pairs) { el(id).replaceChildren(); pairs.forEach(([label,value,note])=>{const c=node('div',null,'card');c.append(node('small',label),node('strong',value),node('small',note||''));el(id).append(c);}); }
function renderWatch() {
  const query=el('watch-search').value.toUpperCase();
  const rows=(quantState?.watchlist?.candidates||[]).filter(r=>`${r.symbol} ${r.sector}`.toUpperCase().includes(query));
  table('watch-full',['Symbol','Sector','ATR %','Prior close ₹','Daily value ₹','Research score'],rows.map(r=>[stockButton(r.symbol),r.sector,number(r.atr_pct),number(r.prev_close),number(r.turnover,0),number(r.score)]));
  text('model-status',human(quantState?.learning?.status));
}
function renderHistory() {
  if(!workspaceState)return;
  const engine=el('history-filter').value, query=el('history-search').value.toUpperCase();
  const rows=workspaceState.history.filter(r=>{const q=(r.source_label||'').startsWith('quant_v3:');return (engine==='all'||(engine==='quant'?q:!q))&&`${r.symbol} ${r.date}`.toUpperCase().includes(query);});
  el('history').replaceChildren();
  rows.forEach(r=>{const tr=node('tr');[r.date,r.symbol,number(r.entry_price),`${(r.source_label||'').startsWith('quant_v3:')?'V3':'Legacy'} · ${human(r.status)}`,number(r.result_return)].forEach(v=>tr.append(node('td',v)));el('history').append(tr);});
  if(!rows.length)cellRow(el('history'),['No matching records','','','','']);
}
function spark(points, width=280, height=55) {
  if(points.length<2)return null;
  const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox',`0 0 ${width} ${height}`);svg.classList.add('chart');svg.setAttribute('aria-label','Recorded price trend');
  const lo=Math.min(...points),hi=Math.max(...points),span=hi-lo||1;
  const path=document.createElementNS(svg.namespaceURI,'polyline');path.setAttribute('points',points.map((p,i)=>`${i/(points.length-1)*width},${height-5-(p-lo)/span*(height-10)}`).join(' '));path.setAttribute('fill','none');path.setAttribute('stroke','#73e5c0');path.setAttribute('stroke-width','2');svg.append(path);return svg;
}
function renderMarkets(data) {
  const instruments=data.market.instruments||[];
  for(const id of ['market-strip','market-board']){
    el(id).replaceChildren();const rows=id==='market-strip'?instruments.filter(r=>['NIFTY 50','BANK NIFTY','SENSEX','USD / INR'].includes(r.name)):instruments;
    if(!rows.length){empty(id,'Market snapshot unavailable. A bounded background refresh is attempted; no prices are inferred.');continue;}
    rows.forEach(r=>{const c=node('article',null,'ticker');c.append(node('small',r.name),node('div',number(r.price),'value'),node('span',`${r.change_pct>=0?'+':''}${number(r.change_pct)}%`,r.change_pct>=0?'positive':'negative'));const chart=spark(r.series||[]);if(chart)c.append(chart);c.append(node('small',`${r.date} · ${r.source}`));el(id).append(c);});
  }
  text('mover-date',`${data.movers_date||'No session'} · ${data.mover_coverage} covered symbols · daily close changes`);
  for(const id of ['gainers','losers'])table(id,['Symbol','Price ₹','Change %'],data[id].map(r=>[stockButton(r.symbol),number(r.price),number(r.change_pct)]));
  text('sector-note',`Equal-weight mean change within covered symbols. ${data.unknown_sector_count} symbols have no sector mapping.`);
  table('sector-board',['Sector','Mean %','Symbols'],data.sectors.map(r=>[r.name,number(r.change_pct),r.samples]));
  table('macro-board',['Series','Value','Observation date'],data.macro.map(r=>[r.name,number(r.value),r.date||'Unknown']));
  text('news-date',data.news_cached_at||'Cache time unknown');el('news-board').replaceChildren();
  const articles=[...data.news].sort((a,b)=>(Date.parse(b.published)||0)-(Date.parse(a.published)||0));
  articles.forEach(r=>{const c=node('article',null,'news-item'), parsed=Date.parse(r.published), age=(Date.now()-parsed)/86400000;
    c.append(node('small',`${r.source||'Source unavailable'} · ${r.published||'Date unknown'} · ${!Number.isFinite(age)?'Unverified date':age>2?'Archive':age<0?'Future date — verify':'Recent publication'}`),node('h3',r.title||'Untitled'));
    const plain=(r.desc||'').replace(/<[^>]*>/g,'');c.append(node('p',plain.slice(0,260)));
    try{const url=new URL(r.url||r.link);if(['http:','https:'].includes(url.protocol)){const a=node('a','Read source ↗');a.href=url.href;a.target='_blank';a.rel='noopener noreferrer';c.append(a);}}catch{}
    el('news-board').append(c);
  });if(!articles.length)empty('news-board','No sourced news has been recorded.');
}
function renderPositions(data) {
  el('position-board').replaceChildren();
  for(const s of [...data.signals].reverse()){
    const p=s.value,o=s.outcome||{},c=node('article',null,'position');c.append(stockButton(s.symbol),node('p',`${s.date} · ${human(o.status||'awaiting entry')} · Reference ₹${number(p.price)} · Structural stop ₹${number(p.stop)}`));
    const fills=o.fills||[],sold=fills.reduce((sum,r)=>sum+r.fraction,0);
    c.append(node('p',`Entry ₹${number(o.entry)} · Net ${o.return_pct==null?'unresolved':number(o.return_pct)+'%'} · Remaining ${o.entry==null?'not entered':number(Math.max(0,1-sold)*100)+'%'}`));
    fills.forEach(f=>c.append(node('div',`${new Date(f.ts*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})} · ${human(f.reason)} · ${number(f.fraction*100)}% at ₹${number(f.price)}`,'fill-row')));el('position-board').append(c);
  }if(!data.signals.length)empty('position-board','No Quant V3 paper positions have been published. Legacy positions remain in recorded history.');
  const closed=data.signals.filter(s=>s.outcome?.resolved&&s.outcome.return_pct!=null),daily={};
  closed.forEach(s=>{daily[s.date]=(daily[s.date]||0)+s.outcome.return_pct/3;});
  let equity=100,peak=100,dd=0;const curve=[100];Object.keys(daily).sort().forEach(d=>{equity*=1+daily[d]/100;peak=Math.max(peak,equity);dd=Math.max(dd,(peak-equity)/peak*100);curve.push(equity);});
  cards('performance-metrics',[['CLOSED FILLS',closed.length],['NET WIN RATE',closed.length?number(closed.filter(s=>s.outcome.return_pct>0).length/closed.length*100)+'%':'Not measured'],['CLOSED EQUITY',closed.length?number(equity):'Not measured','Starting index 100'],['MAX DRAWDOWN',closed.length?number(dd)+'%':'Not measured','Closed-session equity']]);
  el('equity-chart').replaceChildren();const chart=spark(curve,700,160);if(chart)el('equity-chart').append(chart,node('p','Closed-session equity index. Open-position mark-to-market is excluded.','chart-caption'));else empty('equity-chart','The equity curve appears after the first resolved paper fill.');
}
function renderSystem(){
  if(!quantState)return;
  const q=quantState,health=q.data_health||{},quoteHealth=q.quote_health||{},r=q.runtime||{},angel=workspaceState?.angel||{},backfill=workspaceState?.backfill||{},review=q.qualitative_review||{};
  definitions('system-details',[['Runtime',human(r.status)],['Last runtime update',r.updated_at||'Unknown'],['Review ledger rows',q.reviews?.length??0],['Angel session',human(angel.status||'not_configured')],['Angel authenticated',angel.authenticated_at||'No active session'],['Angel session expiry',angel.expires_at||'Unknown'],['Angel instruments',angel.instrument_count??'Not loaded'],['Angel quote verified',`${angel.quote_verified??0} / ${angel.quote_requested??0}`],['Backfill state',human(backfill.status||'not_started')],['Backfill progress',`${backfill.visited??0} / ${backfill.universe??0} symbols`],['Candle source',health.source||'Unknown'],['Last refresh',health.checked_at||'Unknown'],['Updated / failed / deferred',`${health.updated??'—'} / ${health.failed??'—'} / ${health.deferred??'—'}`],['Live quote status',human(quoteHealth.status||'not_checked')],['Live quote source',quoteHealth.source||'No verified source'],['Daily free-only review',review.status||'Not attempted'],['Review provider',review.provider||'No provider used'],['Review model',review.model||'No model used'],['Provider error',review.provider_error||'None'],['Review cooldown',review.cooldown_until?new Date(review.cooldown_until*1000).toLocaleString():'None'],['Preparation seconds',number(q.preparation?.elapsed_seconds)],['Latest cycle seconds',number(r.elapsed_seconds)]]);
}
let contextBusy=false;
async function loadWorkspace(){
  if(contextBusy)return;contextBusy=true;
  try{
    const d=await json('/api/quant/workspace');workspaceState=d;renderMarkets(d);renderHistory();renderPositions(d);renderSystem();
    table('rejection-board',['Gate','Recorded count'],d.rejections.map(r=>[human(r.reason),r.count]));
    table('usage-board',['Integration','Recorded calls'],d.usage.map(r=>[human(r.name),r.calls??'Unknown']));
    table('activity-board',['Session','Symbol','Setup','Decision','Origin'],d.activity.map(r=>[r.date,stockButton(r.symbol),human(r.setup),human(r.reason),human(r.provenance)]));
    el('legacy-board').replaceChildren();d.legacy.forEach(r=>{const c=node('article',null,'news-item');c.append(node('h3',r.name),node('small',r.updated_at||'No recorded timestamp'),node('p',r.available?r.note:'No saved report available'));for(const [key,value] of Object.entries(r.details||{}))c.append(node('p',`${human(key)}: ${value}`));el('legacy-board').append(c);});
    table('pattern-board',['Legacy pattern','Recorded success rate','Samples','Updated'],d.patterns.map(r=>[r.pattern_key,number(r.success_rate),r.sample_count,r.last_market_update||'Unknown']));
    table('model-board',['Version','Status','Training end','Evaluation end','Model net %','Baseline net %','Brier / baseline','Forward trades'],d.models.map(r=>[r.id,r.promoted?'Promoted historically':'Candidate',r.trained_through,r.evaluated_through,number(r.evaluation?.model?.mean_net_pct),number(r.evaluation?.baseline?.mean_net_pct),`${number(r.evaluation?.brier,4)} / ${number(r.evaluation?.base_rate_brier,4)}`,r.evaluation?.forward_recorded?.trades??'Not measured']));
  }catch(error){text('connection','Broader context unavailable · previously displayed context may be stale');}
  finally{contextBusy=false;}
}
let stockRequest=0;
async function openStock(symbol){
  const request=++stockRequest;text('stock-title',symbol);empty('stock-content','Loading recorded stock evidence…');if(!el('stock-dialog').open)el('stock-dialog').showModal();
  try{const d=await json('/api/quant/stock/'+encodeURIComponent(symbol));if(request!==stockRequest)return;
    const parent=el('stock-content');parent.replaceChildren();const bars=d.bars,obs=d.observation,features=obs?.features||{};
    parent.append(node('p',bars.length?`Recorded 5-minute candles · last bar ${new Date(bars.at(-1).ts*1000).toLocaleString('en-IN',{timeZone:'Asia/Kolkata'})} IST · ${bars.at(-1).source}`:'No intraday candles available.','muted'));
    if(bars.length){const svg=document.createElementNS('http://www.w3.org/2000/svg','svg');svg.setAttribute('viewBox','0 0 800 270');svg.classList.add('chart');svg.setAttribute('role','img');svg.setAttribute('aria-label',`${symbol} recorded candlestick chart`);
      const lo=Math.min(...bars.map(b=>b.low)),hi=Math.max(...bars.map(b=>b.high)),span=hi-lo||1,y=p=>235-(p-lo)/span*210;
      for(let i=0;i<bars.length;i++){const b=bars[i],x=55+i*690/bars.length,color=b.close>=b.open?'#73e5c0':'#ff9c9c';const line=document.createElementNS(svg.namespaceURI,'line');for(const [k,v]of Object.entries({x1:x,x2:x,y1:y(b.high),y2:y(b.low),stroke:color}))line.setAttribute(k,v);const rect=document.createElementNS(svg.namespaceURI,'rect');for(const [k,v]of Object.entries({x:x-2,y:Math.min(y(b.open),y(b.close)),width:Math.max(2,Math.min(7,500/bars.length)),height:Math.max(1,Math.abs(y(b.open)-y(b.close))),fill:color}))rect.setAttribute(k,v);const title=document.createElementNS(svg.namespaceURI,'title');title.textContent=`${new Date(b.ts*1000).toLocaleTimeString('en-IN',{timeZone:'Asia/Kolkata'})} O ${number(b.open)} H ${number(b.high)} L ${number(b.low)} C ${number(b.close)} V ${number(b.volume,0)}`;rect.append(title);svg.append(line,rect);}
      for(const price of [lo,(lo+hi)/2,hi]){const label=document.createElementNS(svg.namespaceURI,'text');label.setAttribute('x',0);label.setAttribute('y',y(price));label.textContent=number(price);svg.append(label);}parent.append(svg,node('p','Hover over a candle for OHLCV. This is the last cached session, not a live execution chart.','chart-caption'));
    }
    parent.append(node('h3',`Recorded setup evidence · ${obs?.date||'date unavailable'}`));const metrics=node('div',null,'grid');for(const [k,v]of [['Setup',human(obs?.setup||features.setup)],['Decision',human(obs?.reason||'no recorded observation')],['RVOL',number(features.rvol)],['VWAP ₹',number(features.vwap)],['ATR %',number(features.atr_pct)],['Structural stop ₹',number(features.stop)]]){const c=node('div',null,'card');c.append(node('small',k),node('strong',v));metrics.append(c);}parent.append(metrics,node('p',`Observation: ${obs?.date||'unavailable'} · ${human(obs?.provenance||'unknown')}. Historical labels: ${d.research.samples} filled observations; +7% reached ${d.research.hit7}, +10% reached ${d.research.hit10}. Overlapping observations are not independent trades.`,'muted'));
    if(d.catalyst)parent.append(node('h3','Recorded catalyst'),node('p',d.catalyst.headline||d.catalyst.summary||'Saved catalyst record has no headline.'));else parent.append(node('p','No verified catalyst recorded for this symbol.','muted'));
  }catch(error){if(request===stockRequest)empty('stock-content','Stock evidence unavailable. No data inferred.');}
}
el('stock-close').addEventListener('click',()=>el('stock-dialog').close());
el('stock-dialog').addEventListener('click',event=>{if(event.target===el('stock-dialog'))el('stock-dialog').close();});
el('watch-search').addEventListener('input',renderWatch);el('history-search').addEventListener('input',renderHistory);el('history-filter').addEventListener('change',renderHistory);
el('refresh').addEventListener('click',loadWorkspace);
refresh(); history(); powerStatus(); loadWorkspace();setInterval(refresh,15000);setInterval(powerStatus,30000);setInterval(loadWorkspace,60000);
