// MarketMind Pro — Research and Advisory Only
// This system does NOT place trades. All picks are for research purposes.

const REFRESH_INTERVAL_MS = 60_000; // 60 seconds

// ── Tab switching ──────────────────────────────────────────────────────────
function switchTab(name) {
  document.querySelectorAll('.tab-content').forEach(el => el.classList.remove('active'));
  document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
  document.getElementById(`tab-${name}`).classList.add('active');
  document.querySelectorAll('.tab-btn').forEach(btn => {
    if (btn.getAttribute('onclick').includes(name)) btn.classList.add('active');
  });
  loadTab(name);
}

function loadTab(name) {
  if (name === 'picks')    loadPicks();
  if (name === 'tracking') loadTracking();
  if (name === 'results')  loadResults();
  if (name === 'history')   loadHistory();
  if (name === 'accuracy')  loadAccuracy();
  if (name === 'eod')      loadEOD();
}

// ── Helpers ────────────────────────────────────────────────────────────────
const fmt = (v, dec=2) => (v == null || v === '') ? '—' : Number(v).toFixed(dec);
const fmtRupee = v => v == null ? '—' : `₹${Number(v).toFixed(2)}`;

function marketBadge(status) {
  const map = {
    'Open':    ['badge-green',  '● Open'],
    'Closed':  ['badge-red',    '● Closed'],
    'Holiday': ['badge-yellow', '● Holiday'],
    'Weekend': ['badge-grey',   '● Weekend'],
  };
  const [cls, label] = map[status] || ['badge-grey', status || '—'];
  return `<span class="badge ${cls}">${label}</span>`;
}

function statusBadge(status) {
  if (!status) return '<span class="badge badge-grey">—</span>';
  const map = {
    'pending':  ['badge-blue',   'Tracking'],
    'tp_hit':   ['badge-green',  'TP Hit ✅'],
    'sl_hit':   ['badge-red',    'SL Hit 🛑'],
    'open_eod': ['badge-grey',   'EOD'],
  };
  const [cls, label] = map[status] || ['badge-grey', status];
  return `<span class="badge ${cls}">${label}</span>`;
}

function returnColour(v) {
  if (v == null) return 'neutral';
  return v > 0 ? 'positive' : v < 0 ? 'negative' : 'neutral';
}

function setRefreshLabel() {
  const now = new Date();
  document.getElementById('last-refresh').textContent =
    `Last refresh: ${now.toLocaleTimeString('en-IN')}`;
}

// ── Tab 1: Today's Picks ───────────────────────────────────────────────────
async function loadPicks() {
  try {
    const data = await fetch('/api/picks').then(r => r.json());

    // Market badge
    document.getElementById('market-badge').outerHTML =
      marketBadge(data.market_status).replace(
        '<span', '<span id="market-badge"'
      );
    // Fallback update
    const mb = document.getElementById('market-badge');
    if (mb) {
      const map = { 'Open':'badge-green','Closed':'badge-red','Holiday':'badge-yellow','Weekend':'badge-grey' };
      mb.className = `badge ${map[data.market_status] || 'badge-grey'}`;
      mb.textContent = data.market_status === 'Open' ? '● Open' :
                       data.market_status === 'Closed' ? '● Closed' :
                       data.market_status === 'Holiday' ? '● Holiday' : '● Weekend';
    }

    // Metrics
    document.getElementById('m-scanned').textContent = data.n_universe?.toLocaleString() || '—';
    document.getElementById('m-picks').textContent   = data.picks?.length || '0';
    document.getElementById('m-date').textContent    = data.date || '—';

    const picks = data.picks || [];
    const avgConf = picks.length
      ? (picks.reduce((s, p) => s + (p.confidence || 0), 0) / picks.length).toFixed(1) + '%'
      : '—';
    document.getElementById('m-confidence').textContent = avgConf;

    // Pick cards
    const container = document.getElementById('picks-container');
    if (!picks.length) {
      container.innerHTML = '<p style="color:var(--muted);grid-column:1/-1">No picks today yet. Bot runs at 09:00 AM IST.</p>';
      return;
    }

    container.innerHTML = picks.map(p => {
      const cardClass = {
        'tp_hit':'tp', 'sl_hit':'sl', 'pending':'track', 'open_eod':'eod'
      }[p.status] || 'track';

      const retHtml = p.result_return != null
        ? `<div class="pick-return ${returnColour(p.result_return)}">
             ${p.result_return >= 0 ? '+' : ''}${fmt(p.result_return)}%
           </div>` : '';

      const conf = p.confidence || 0;
      const reasons = p.signal_reasons || '';

      return `
        <div class="pick-card ${cardClass}">
          <div class="pick-rank">Rank #${p.rank}</div>
          <div class="pick-symbol">${p.symbol}</div>
          <div class="pick-status">${statusBadge(p.status)}</div>
          <div class="pick-levels">
            <div class="pick-level-item">
              <div class="pick-level-label">Entry</div>
              <div class="pick-level-value entry-val">${fmtRupee(p.entry_price)}</div>
            </div>
            <div class="pick-level-item">
              <div class="pick-level-label">Stop Loss</div>
              <div class="pick-level-value sl-val">${fmtRupee(p.sl_price)}</div>
            </div>
            <div class="pick-level-item">
              <div class="pick-level-label">Target</div>
              <div class="pick-level-value target-val">${fmtRupee(p.target_price)}</div>
            </div>
          </div>
          <div class="pick-upside">▲ Upside: ${fmt(p.upside_pct, 1)}%</div>
          <div class="pick-conf-label">Confidence: ${fmt(conf, 1)}%</div>
          <div class="conf-bar-track">
            <div class="conf-bar-fill" style="width:${Math.min(conf,100)}%"></div>
          </div>
          ${retHtml}
          ${reasons ? `<div class="pick-reasons">📌 ${reasons}</div>` : ''}
        </div>`;
    }).join('');

  } catch (e) {
    console.error('loadPicks:', e);
  }
}

// ── Tab 2: Results ─────────────────────────────────────────────────────────
async function loadResults() {
  try {
    const data = await fetch('/api/results').then(r => r.json());
    const acc  = data.accuracy || {};

    document.getElementById('results-metrics').innerHTML = `
      <div class="metric-card">
        <div class="metric-label">TP Hits</div>
        <div class="metric-value" style="color:var(--green)">${acc.tp_count ?? '—'}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">SL Hits</div>
        <div class="metric-value" style="color:var(--red)">${acc.sl_count ?? '—'}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Accuracy</div>
        <div class="metric-value">${acc.accuracy != null ? fmt(acc.accuracy,1)+'%' : '—'}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Avg Return</div>
        <div class="metric-value ${returnColour(acc.avg_return)}">
          ${acc.avg_return != null ? (acc.avg_return >= 0 ? '+' : '') + fmt(acc.avg_return) + '%' : '—'}
        </div>
      </div>`;

    const tbody = document.getElementById('results-tbody');
    const picks = data.picks || [];
    tbody.innerHTML = picks.length ? picks.map(p => `
      <tr>
        <td>${p.rank}</td>
        <td style="color:var(--blue);font-weight:600">${p.symbol}</td>
        <td>${fmtRupee(p.entry_price)}</td>
        <td style="color:var(--red)">${fmtRupee(p.sl_price)}</td>
        <td style="color:var(--green)">${fmtRupee(p.target_price)}</td>
        <td>${statusBadge(p.status)}</td>
        <td class="${returnColour(p.result_return)}">
          ${p.result_return != null ? (p.result_return >= 0 ? '+' : '') + fmt(p.result_return) + '%' : '—'}
        </td>
      </tr>`).join('') : '<tr><td colspan="7" style="color:var(--muted);text-align:center;padding:24px">No results yet today.</td></tr>';

  } catch (e) { console.error('loadResults:', e); }
}

// ── Tab 3: History ─────────────────────────────────────────────────────────
async function loadHistory() {
  try {
    const data = await fetch('/api/history').then(r => r.json());

    document.getElementById('history-metrics').innerHTML = `
      <div class="metric-card">
        <div class="metric-label">Total TP</div>
        <div class="metric-value" style="color:var(--green)">${data.overall_tp ?? '—'}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Total SL</div>
        <div class="metric-value" style="color:var(--red)">${data.overall_sl ?? '—'}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Overall Accuracy</div>
        <div class="metric-value">${data.overall_accuracy != null ? data.overall_accuracy + '%' : '—'}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Total Picks</div>
        <div class="metric-value">${data.total_closed ?? '—'}</div>
      </div>`;

    const picks = data.picks || [];
    document.getElementById('history-tbody').innerHTML = picks.length
      ? picks.map(p => `
          <tr>
            <td style="color:var(--muted)">${p.date}</td>
            <td>${p.rank}</td>
            <td style="color:var(--blue);font-weight:600">${p.symbol}</td>
            <td>${fmtRupee(p.entry_price)}</td>
            <td style="color:var(--red)">${fmtRupee(p.sl_price)}</td>
            <td style="color:var(--green)">${fmtRupee(p.target_price)}</td>
            <td>${statusBadge(p.status)}</td>
            <td class="${returnColour(p.result_return)}">
              ${p.result_return != null ? (p.result_return >= 0 ? '+' : '') + fmt(p.result_return) + '%' : '—'}
            </td>
          </tr>`).join('')
      : '<tr><td colspan="8" style="color:var(--muted);text-align:center;padding:24px">No history yet.</td></tr>';

  } catch (e) { console.error('loadHistory:', e); }
}

// ── Tab 4: Accuracy ─────────────────────────────────────────────
async function loadAccuracy() {
  try {
    const res = await fetch('/api/dashboard_accuracy').then(r => r.json());

    const accuracy = res.accuracy_pct || 0;
    const total = res.total_picks || 0;
    const tp = res.tp_hits || 0;
    const sl = res.sl_hits || 0;
    const hold = res.holds || 0;

    document.getElementById('acc-pct').textContent = accuracy + '%';
    document.getElementById('acc-bar').style.width = accuracy + '%';

    document.getElementById('accuracy-metrics').innerHTML = `
      <div class="metric-card">
        <div class="metric-label">Total Picks</div>
        <div class="metric-value">${total}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">TP Hit</div>
        <div class="metric-value text-green">${tp}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">SL Hit</div>
        <div class="metric-value text-red">${sl}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Hold</div>
        <div class="metric-value">${hold}</div>
      </div>
    `;
  } catch (e) {
    console.error('Accuracy error:', e);
  }
}

    // Pattern metrics
    document.getElementById('pattern-metrics').innerHTML = `
      <div class="metric-card">
        <div class="metric-label">Total Patterns</div>
        <div class="metric-value">${accData.total_patterns ?? '—'}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Weekly-Proven</div>
        <div class="metric-value" style="color:var(--purple)">${accData.weekly_patterns ?? '—'}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Anti-Patterns</div>
        <div class="metric-value" style="color:var(--red)">${accData.anti_patterns ?? '—'}</div>
      </div>
      <div class="metric-card">
        <div class="metric-label">Trading Days</div>
        <div class="metric-value">${overall.trading_days ?? '—'}</div>
      </div>`;

    // Daily bar chart (last 30 days)
    const daily = (accData.daily || []).slice(0, 30).reverse();
    const maxAcc = daily.length ? Math.max(...daily.map(d => d.accuracy || 0), 1) : 100;
    const barsHtml = daily.map(d => {
      const h = Math.round((d.accuracy || 0) / maxAcc * 80);
      const colour = (d.accuracy || 0) >= 75 ? 'var(--green)' :
                     (d.accuracy || 0) >= 50 ? 'var(--blue)' : 'var(--red)';
      const shortDate = (d.date || '').slice(5); // MM-DD
      return `
        <div class="bar-item" title="${d.date}: ${fmt(d.accuracy,1)}% accuracy">
          <div class="bar-fill" style="height:${h}px;background:${colour}"></div>
          <div class="bar-label">${shortDate}</div>
        </div>`;
    }).join('');
    document.getElementById('day-bars').innerHTML = barsHtml ||
      '<p style="color:var(--muted);margin:auto">No daily data yet.</p>';

    // Patterns table
    const patterns = patData.patterns || [];
    document.getElementById('patterns-tbody').innerHTML = patterns.length
      ? patterns.map(p => {
          const levelClass = { weekly:'proven-weekly', daily:'proven-daily', none:'proven-none' }[p.proven_level] || '';
          const antiHtml   = p.is_anti_pattern ? '<span class="anti-yes">YES</span>' : '—';
          const srColour   = p.success_rate >= 0.6 ? 'positive' : p.success_rate >= 0.4 ? '' : 'negative';
          return `
            <tr>
              <td style="font-size:11px;max-width:300px;overflow:hidden;text-overflow:ellipsis"
                  title="${p.pattern_key}">${p.pattern_key}</td>
              <td class="${srColour}">${fmt(p.success_rate * 100, 1)}%</td>
              <td>${p.sample_count}</td>
              <td class="${levelClass}">${p.proven_level}</td>
              <td>${antiHtml}</td>
              <td style="color:var(--muted)">${p.source || '—'}</td>
            </tr>`;
        }).join('')
      : '<tr><td colspan="6" style="color:var(--muted);text-align:center;padding:24px">No patterns learned yet. Bot will learn after market close.</td></tr>';

  } catch (e) { console.error('loadAccuracy:', e); }
}

// ── Tab 2: Live Tracking ────────────────────────────────────────────
async function loadTracking() {
  try {
    const res = await fetch('/api/tracking').then(r => r.json());
    const picks = res.picks || {};

    document.getElementById('track-total').textContent = res.total || 0;
    document.getElementById('track-active').textContent = res.active || 0;
    document.getElementById('track-tp').textContent = res.target_hit || 0;
    document.getElementById('track-sl').textContent = res.stopped_out || 0;

    const container = document.getElementById('tracking-container');
    if (!container) return;

    container.innerHTML = '';
    for (const sym in picks) {
      const p = picks[sym];
      const status = p.status || 'unknown';
      const pnl = p.pnl_pct || 0;

      const card = document.createElement('div');
      card.className = 'pick-card';
      card.innerHTML = `
        <div class="pick-header">
          <span class="pick-symbol">${sym}</span>
          <span class="badge ${status === 'target_hit' ? 'badge-green' : status === 'stopped_out' ? 'badge-red' : 'badge-blue'}">${status}</span>
        </div>
        <div class="pick-prices">
          <div><span>Entry:</span> <b>₹${p.entry_price || 0}</b></div>
          <div><span>Current:</span> <b>₹${p.current_price || 0}</b></div>
          <div><span>P&L:</span> <b class="${pnl >= 0 ? 'text-green' : 'text-red'}">${pnl >= 0 ? '+' : ''}${pnl}%</b></div>
        </div>
        <div class="pick-sl">
          <span>SL: ₹${p.sl_price || 0}</span>
          <span>TP: ₹${p.tp_price || 0}</span>
        </div>
      `;
      container.appendChild(card);
    }
  } catch (e) {
    console.error('Tracking error:', e);
  }
}

// ── Tab 5: EOD Report ─────────────────────────────────────────────
async function loadEOD() {
  try {
    const res = await fetch('/api/dashboard_eod').then(r => r.json());

    const gainers = res.top_gainers || [];
    const losers = res.top_losers || [];

    const gainContainer = document.getElementById('eod-gainer-container');
    if (gainContainer) {
      gainContainer.innerHTML = '';
      gainers.slice(0, 10).forEach((g, i) => {
        const card = document.createElement('div');
        card.className = 'pick-card';
        card.innerHTML = `
          <div class="pick-header">
            <span class="pick-symbol">${g.symbol}</span>
            <span class="badge badge-green">+${g.gain_pct}%</span>
          </div>
          <div class="pick-prices">
            <div><span>Price:</span> <b>₹${g.price}</b></div>
            <div><span>Sector:</span> <b>${g.sector}</b></div>
          </div>
          <div class="pick-sl"><i>${g.reason || ''}</i></div>
        `;
        gainContainer.appendChild(card);
      });
    }

    const loseContainer = document.getElementById('eod-loser-container');
    if (loseContainer) {
      loseContainer.innerHTML = '';
      losers.slice(0, 10).forEach((l, i) => {
        const card = document.createElement('div');
        card.className = 'pick-card';
        card.innerHTML = `
          <div class="pick-header">
            <span class="pick-symbol">${l.symbol}</span>
            <span class="badge badge-red">${l.gain_pct}%</span>
          </div>
          <div class="pick-prices">
            <div><span>Price:</span> <b>₹${l.price}</b></div>
            <div><span>Sector:</span> <b>${l.sector}</b></div>
          </div>
        `;
        loseContainer.appendChild(card);
      });
    }
  } catch (e) {
    console.error('EOD error:', e);
  }
}

// ── Auto-refresh ───────────────────────────────────────────────────────────
function refreshAll() {
  const active = document.querySelector('.tab-content.active');
  if (active) {
    const name = active.id.replace('tab-', '');
    loadTab(name);
  }
  setRefreshLabel();
}

// ── Init ───────────────────────────────────────────────────────────────────
document.addEventListener('DOMContentLoaded', () => {
  loadPicks();
  setRefreshLabel();
  setInterval(refreshAll, REFRESH_INTERVAL_MS);
});
