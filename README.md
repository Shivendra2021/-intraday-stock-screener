# MarketMind Pro / Intraday Stock Screener

Research-only intraday stock screening bot and dashboard for NSE/BSE symbols.

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
python run_dashboard.py           # dashboard
python -m unittest discover -v    # tests
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
