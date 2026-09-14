# Quant V3: implementation, evidence, and operation

The software now follows the requested intraday workflow. Its ability to identify
profitable +7–10% opportunities is **not established**. Neither daily improvement,
three qualifying stocks every day, nor 10–20x total speed is promised.

## Your goal versus the system

| Goal | Previous path reviewed | Quant V3 |
|---|---|---|
| Three strong stocks | Rejected drafts could be added back to fill slots; missing second-brain output could be treated as agreement | Maximum three unique symbols per session; no forced backfill; no model or failed quote means abstention |
| +7–10% intraday opportunity | Mixed daily open-to-high labels, fixed targets, and whole-position return reporting | Targets measured from next eligible simulated entry; half exits at +7%, half at +10%; stop and 15:20 exit policy |
| Morning decision | Premarket selection/catch-up logic | Watchlist from 08:45; completed opening bars; confirmation after 09:30 through 11:00 IST; earliest current setup calculation is 09:35 |
| Mathematical ranking | AI debate and heuristic scores could appear as confidence | Identical point-in-time features, regularized logistic probabilities, separate calibration dates, regularized expected net return model |
| Learn from mistakes | Several separate learning loops, sparse audited outcomes | Immutable observations, including rejections; chronological simulated outcomes; date-separated evaluation; candidate/champion promotion gates |
| Faster operation | Overlapping agents and repeated downloads | One scheduler, durable candle cache, batch downloads with bounded child processes, incremental overlap, cached daily features, resumable research |
| Reliable results | Missing data and inconsistent accounting could inflate apparent accuracy | No fabricated metrics; missing entry/exit candles remain unresolved; partial position accounting and costs; net-positive fills separated from target touches |
| Free/existing data | Multiple providers and optional external AI calls | Yahoo history; existing Dhan credentials or NSE public quotes; no new purchase or paid integration |
| Useful dashboard on startup | Historical/current state could be confused | Saved history appears immediately; today's slots contain only today's Quant V3 signals |

## What the signal means

1. Prior completed daily candles determine liquidity, ATR, trend, and RSI. The
   most recent completed trading session must be present. Suspect corporate-action
   jumps are rejected.
2. Complete five-minute candles determine opening expansion, compression breakout,
   or VWAP continuation. Relative volume compares cumulative volume with prior
   sessions at the same clock time, requiring at least five comparable sessions.
3. Liquidity, price, participation, and structural-stop gates reject unsuitable
   candidates. Current defaults require at least ₹2 crore median daily traded
   value, price ₹20, RVOL 1.5, and 0.5–3% structural risk.
4. An accepted model estimates probabilities of reaching +7% and +10% under the
   fixed exit policy. A candidate needs estimated P(+7%) at least 30% and positive
   modeled net expectation. These thresholds are conservative design choices,
   not demonstrated optimal settings.
5. Before publication, a quote must identify EQ series, fresh timestamp (90 seconds),
   valid bid/ask, spread at most 0.30%, and verified upper-band headroom for +10%.
   Missing verification blocks publication. Sector duplication is limited when
   sector data is known; unknown sectors cannot provide a diversification guarantee.
6. Publication reserves one of three daily slots. Paper entry occurs at the next
   boundary after a full processing interval: a 09:35 decision targets 09:40.
   Quotes that already moved more than 1% or signals published after that boundary
   are rejected. Entry gaps above 1% cancel the fill but still consume the slot.
7. The initial structural stop applies before targets when both occur in the same
   candle. After the first target, the runner stop becomes +3.5%, effective from
   the following candle. Gap stops fill at the worse opening price. Remaining
   quantity exits at the complete 15:20 boundary.

**A +10% target touch is not a +10% portfolio return.** With half sold at +7% and
half at +10%, the gross position return is 8.5% before modeled costs/slippage.
The defaults model 20 basis points round trip plus 5 basis points per fill. Actual
fees, taxes, market impact, and execution may differ. No leverage is assumed.
Two recorded net losses stop additional selections for that session.

## Learning and validation

Daily research labels only outcomes after each decision timestamp. Training,
calibration, and evaluation use different dates (50% / 20% / 30%). Current minimums
are 30 eligible sessions and 300 samples, plus sufficient positive and negative
examples for both targets. Correlated observations are not independent trials;
uncertainty in selected returns is clustered by session.

Promotion requires at least 20 evaluated filled setups over five sessions, a
positive lower mean-return bound, probability calibration better than a base-rate
predictor, and better mean return than the baseline and eligible prior champion.
Evaluation sessions cannot be reused to claim a fresh promotion.

Because historical downloads use the current available universe/watchlist, they
have selection/survivorship bias and lack historical spread, depth, eligibility,
and circuit-limit evidence. Historical replay alone cannot activate a model.
Promotion additionally requires qualifying outcomes from candidates recorded during
live sessions on later evaluation dates. These are still simulated outcomes, not
broker execution. No mechanism guarantees improvement every day.

Candidate models and evaluations are versioned in SQLite. Current models expire
after 30 calendar days without sufficiently recent evaluation. This can lead to
extended evidence collection and zero confirmed picks.

## Measurements from this upgrade

- Initial preparation with a 120-second budget **per download phase**: 480 symbols
  downloaded with daily history, 447 passed initial daily feature checks, 98/100
  watchlist symbols downloaded intraday history. Total 159.305 seconds. Configured
  universe: 2,486. This was partial coverage, not a complete universe scan.
- Three-stock network refresh: 3.042 seconds. Same candle-bucket refresh:
  0.003 seconds, three cache hits, zero new downloads. This is a cache benchmark,
  **not** an old-versus-new full pipeline speed comparison.
- Dashboard `/api/quant`: 200 response in approximately 0.049 seconds during the
  local check. The dashboard uses recorded state and does not perform market scans.
- The completed bootstrap replay had 174 eligible observations on 15 sessions. Model
  status was `insufficient_evidence`; later replay updates are visible in the
  dashboard and `tools/quant.py status`. No strategy accuracy claim follows from
  the download or observation count.
- The final offline suite includes 29 Quant V3 regression cases. Sixteen legacy
  market-data integration cases are opt-in; skipping them is not a claim that
  live broker/data integration has passed.
- Provider audit: Yahoo history returned data; Dhan client ID/token were missing;
  NSE returned no usable quote. Live quote readiness is therefore unverified.

## Run it

From the repository directory, start the scheduler and dashboard in separate terminals:

```powershell
.\.venv\Scripts\python.exe main.py
.\.venv\Scripts\python.exe dashboard\app.py
```

Open `http://127.0.0.1:5001`. Existing `run_dashboard.ps1` remains usable. Restart
existing Python processes after an upgrade so they load the new modules. The
dashboard's scheduler button starts or pauses the local core.

Useful administration commands (no notifications by default):

```powershell
.\.venv\Scripts\python.exe tools\quant.py audit
.\.venv\Scripts\python.exe tools\quant.py prepare --budget 120
.\.venv\Scripts\python.exe tools\quant.py replay --budget 240
.\.venv\Scripts\python.exe tools\quant.py train
.\.venv\Scripts\python.exe tools\quant.py cycle --offline
.\.venv\Scripts\python.exe tools\quant.py benchmark --budget 30
.\.venv\Scripts\python.exe tools\quant.py status
```

Use `--db path/to/research.db` for a separate research store. The normal scheduler
checks once per minute, avoids overlapping runs, respects the existing market
holiday calendar, and performs post-market reconciliation/learning. Startup
preparation defaults to 45 seconds per download phase to allow an early partial
watchlist; it does not wait for full-universe history. Daily and broad-scan cursors
resume coverage, and historical replay rotates through symbols within its budget.

Existing Dhan credentials belong in `.env` as `DHAN_CLIENT_ID` and
`DHAN_ACCESS_TOKEN`, if the existing account has the required data access. Do not
put credentials into source code or reports. Public-source availability is not
guaranteed. A missing provider is displayed and blocks confirmations.

## Files and verification

`modules/quant_data.py`, `quant_features.py`, `quant_outcomes.py`, `quant_learning.py`,
`quant_store.py`, `quant_engine.py`, and `quant_runtime.py` implement the new flow.
`data/quant.db` contains bars, observations, outcomes, signals, models, and resumable
state. Original `data/history.db` is retained; new signals are mirrored with stable
`quant_v3:` identifiers. Original historical returns have not been reclassified as
validated Quant V3 results. Legacy modules remain available behind
`QUANT_ENABLED=False`, but are not the new default selection path.

```powershell
.\.venv\Scripts\python.exe -B -m pytest tests --ignore=tests/e2e -q
```

Tests run with isolated databases/files and external requests blocked. The legacy
scanner subprocess integration suite is opt-in with `--run-market-integration`;
it requires real market data. Quant regression tests exercise timestamp precision,
future-data exclusion, partial exits, same-bar ambiguity, gap entry/stop handling,
missing candles, quote gates, date-valid models, historical-only promotion
rejection, idempotency, three-slot limits, cache reuse, and dashboard controls.
