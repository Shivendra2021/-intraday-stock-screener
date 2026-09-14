# MarketMind Pro / Intraday Stock Screener

Research-only intraday stock screening bot and dashboard for NSE/BSE symbols.

## Quant V3 (default runtime)

The current engine builds a premarket watchlist, then allows **up to three paper
setups after 09:30 IST**. It targets +7%/+10% from simulated entry, validates fresh
quotes and price-band headroom, and rejects weak or unverified setups. It does
not guarantee those returns or force three selections.

See [the upgrade report and operating guide](docs/QUANT_V3.md) for the comparison,
model promotion requirements, measurements, and current data limitations.

```powershell
.\.venv\Scripts\python.exe main.py                     # scheduler
.\.venv\Scripts\python.exe dashboard\app.py            # localhost:5001
.\.venv\Scripts\python.exe tools\quant.py status        # saved state, no alert
.\.venv\Scripts\python.exe tools\quant.py audit         # existing/free feed checks
.\.venv\Scripts\python.exe tools\quant.py prepare       # initialize/resume history
.\.venv\Scripts\python.exe tools\quant.py learn --budget 240
.\.venv\Scripts\python.exe -m pytest tests --ignore=tests/e2e -q
```

Quant data lives separately in `data/quant.db`; original history is retained.
`QUANT_ENABLED=True` is the default. Legacy agent loops do not run on the quant
selection path. Administration commands send no messages unless `--notify` is
explicitly supplied. Normal scheduler operation uses the existing alert settings.

## Setup

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt -c constraints.txt
python setup_and_verify.py
```

## Environment variables

Create a `.env` file as needed:

```env
DRY_RUN=True
TELEGRAM_BOT_TOKEN=
TELEGRAM_CHAT_ID=
OPENROUTER_GROK_KEY=
OPENROUTER_GPT_KEY=
OPENROUTER_BASE_URL=https://openrouter.ai/api/v1/chat/completions
```

## Common commands

```powershell
python main.py                    # scheduled bot
python dashboard/app.py           # dashboard
python -m pytest tests --ignore=tests/e2e -q  # isolated offline tests
python -m app.research.intraday_pattern_scan --period 2y --top 30 --threshold 5
```

## Audit logs

Morning pipeline decisions are appended to:

```text
data/morning_decisions.jsonl
```

Each line records the stage, timestamp, candidates/picks, and final dual-brain agreement status.

## Safety disclaimer

This project is for research and advisory analysis only. It does not place trades. Past pattern performance does not guarantee future returns.
