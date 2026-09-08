# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.

import os
from dotenv import load_dotenv

load_dotenv()

# ── Market Timing ─────────────────────────────────────────────────────────────
MARKET_OPEN              = "09:15"
MARKET_CLOSE             = "15:30"
ANALYSIS_START           = "08:00"
PRELIMINARY_PICKS_TIME   = "08:30"
FINAL_PICKS_TIME         = "09:00"
TRACKING_INTERVAL_MINUTES = 5
PRECLOSE_SCAN_TIME       = "15:00"
MARKET_LEARNER_START     = "15:35"
LEARNER_START            = "15:45"
WEEKLY_REVIEW_TIME       = "16:00"
EOD_OUTCOME_BRAIN_TIME   = os.getenv("EOD_OUTCOME_BRAIN_TIME", "15:40")

# ── Morning Scan Schedule ─────────────────────────────────────────────
PREMARKET_BOT_START_TIME     = os.getenv("PREMARKET_BOT_START_TIME", "07:30")
MORNING_UNIVERSE_SCAN_START  = os.getenv("MORNING_UNIVERSE_SCAN_START", "07:50")
MORNING_UNIVERSE_SCAN_END    = os.getenv("MORNING_UNIVERSE_SCAN_END", "08:20")
MORNING_DEEP_RESEARCH        = os.getenv("MORNING_DEEP_RESEARCH", "08:20")
MORNING_DEEP_RESEARCH_END    = os.getenv("MORNING_DEEP_RESEARCH_END", "08:45")
MORNING_DEBATE_TIME          = os.getenv("MORNING_DEBATE_TIME", "08:45")
MORNING_FINAL_PICKS          = os.getenv("MORNING_FINAL_PICKS", "08:55")
MORNING_CATCHUP_END          = os.getenv("MORNING_CATCHUP_END", "09:25")

# ── Universe Scanner Config ────────────────────────────────────────────
MORNING_SCAN_WORKERS = 16
MORNING_SCAN_MIN_STOCKS = 20
MORNING_SCAN_MAX_TIME_MINUTES = 40
UNIVERSE_SCAN_BATCH_SIZE = 125

# ── Dual Brain Config ─────────────────────────────────────────────────
DEBATE_REQUIRE_BOTH_AGREE = True
DEBATE_MAX_ROUNDS = 3
DEBATE_LOG_PATH = "data/dual_brain_debates.json"

# ── Winner Finder Config ────────────────────────────────────────────────
INTRADAY_MIN_RETURN_PCT = 7.0
WINNER_FINDER_WORKERS = 8

# ── Pattern Learner Config ─────────────────────────────────────────
PATTERN_MIN_WINNERS = 5
PATTERN_CONFIDENCE_THRESHOLD = 0.6
PATTERNS_FILE = "data/discovered_patterns.json"
PATTERN_LEARNER_RUN_TIME = "16:00"
AFTER_MARKET_LEARNING_TIME = os.getenv("AFTER_MARKET_LEARNING_TIME", "15:50")

# ── Pick Selection ─────────────────────────────────────────────────────────────
TOP_N_PICKS              = 3
MIN_SCORE_THRESHOLD      = 55
MIN_TARGET_MOVE_PCT      = 5.0
MAX_TARGET_MOVE_PCT      = 8.0
SL_ATR_MULTIPLIER        = 1.5
MAX_SL_PCT               = 2.0
MIN_RISK_REWARD          = 2.0

# ── Filters ────────────────────────────────────────────────────────────────────
MIN_VOLUME_FILTER        = 50_000
MIN_PRICE_FILTER         = 50

# ── Paths ──────────────────────────────────────────────────────────────────────
DB_PATH                  = "data/history.db"
DAILY_PICKS_JSON_PATH    = "data/daily_picks_history.json"
LOG_PATH                 = "logs/bot.log"
OUTPUT_DIR               = "output/"

# ── Telegram ───────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID         = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Optional Broker ────────────────────────────────────────────────────────────
ZERODHA_API_KEY          = os.getenv("ZERODHA_API_KEY", "")
ZERODHA_ACCESS_TOKEN     = os.getenv("ZERODHA_ACCESS_TOKEN", "")

# ── AI Brain — OpenRouter (Grok primary, GPT fallback) ─────────────────────────
OPENROUTER_GROK_KEY      = os.getenv("OPENROUTER_GROK_KEY", "")
OPENROUTER_GPT_KEY       = os.getenv("OPENROUTER_GPT_KEY", "")
OPENROUTER_BASE_URL      = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
GROK_MODEL               = os.getenv("GROK_MODEL", "x-ai/grok-3-mini")
GPT_MODEL                = os.getenv("GPT_MODEL", "openai/gpt-4o")

# Groq API (not Grok/xAI). Used as a controlled DeepSeek-R1 reasoning fallback
# for dashboard reviews and after-market learning, not for every scan cycle.
GROQ_API_KEY             = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL            = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1/chat/completions")
GROQ_DEEPSEEK_MODEL      = os.getenv("GROQ_DEEPSEEK_MODEL", "qwen/qwen3.6-27b")
GROQ_DEEPSEEK_ENABLED    = os.getenv("GROQ_DEEPSEEK_ENABLED", "True").strip().lower() in ("true", "1", "yes")
GROQ_DEEPSEEK_TIMEOUT_SECONDS = int(os.getenv("GROQ_DEEPSEEK_TIMEOUT_SECONDS", "60"))

# Legacy XAI fields (kept for backward compatibility — now point to OpenRouter)
XAI_API_KEY              = os.getenv("XAI_API_KEY", OPENROUTER_GROK_KEY)
XAI_MODEL                = os.getenv("XAI_MODEL", GROK_MODEL)
XAI_BASE_URL             = os.getenv("XAI_BASE_URL", OPENROUTER_BASE_URL)
XAI_BRAIN_ENABLED        = os.getenv("XAI_BRAIN_ENABLED", "True").strip().lower() in ("true", "1", "yes")
XAI_BRAIN_REVIEW_ALERTS  = os.getenv("XAI_BRAIN_REVIEW_ALERTS", "True").strip().lower() in ("true", "1", "yes")
XAI_BRAIN_TIMEOUT_SECONDS = int(os.getenv("XAI_BRAIN_TIMEOUT_SECONDS", "60"))
XAI_BRAIN_MIN_INTERVAL_SECONDS = int(os.getenv("XAI_BRAIN_MIN_INTERVAL_SECONDS", "0"))
XAI_BRAIN_MAX_DAILY_CALLS = int(os.getenv("XAI_BRAIN_MAX_DAILY_CALLS", "200"))

# ── News APIs ──────────────────────────────────────────────────────────────────
NEWSAPI_KEY              = os.getenv("NEWSAPI_KEY", "")
THENEWSAPI_KEY           = os.getenv("THENEWSAPI_KEY", "")

# ── Price Validation ───────────────────────────────────────────────────────────
PRICE_VALIDATION_MAX_SPREAD_PCT  = float(os.getenv("PRICE_VALIDATION_MAX_SPREAD_PCT", "2.0"))
PRICE_VALIDATION_MIN_SOURCES     = int(os.getenv("PRICE_VALIDATION_MIN_SOURCES", "1"))
BROKER_QUOTE_REQUIRED            = os.getenv("BROKER_QUOTE_REQUIRED", "False").strip().lower() in ("true", "1", "yes")
PATTERN_MIN_BACKTEST_TRADES      = int(os.getenv("PATTERN_MIN_BACKTEST_TRADES", "3"))
PATTERN_MIN_HIT_RATE             = float(os.getenv("PATTERN_MIN_HIT_RATE", "0.50"))
PATTERN_MIN_AVG_RETURN           = float(os.getenv("PATTERN_MIN_AVG_RETURN", "0.10"))

# ── Universe ───────────────────────────────────────────────────────────────────
UNIVERSE_MODE                    = os.getenv("UNIVERSE_MODE", "small_midcap").strip().lower() # 'small_midcap' or 'all'
INTRADAY_MAX_MARKET_CAP_CR       = float(os.getenv("INTRADAY_MAX_MARKET_CAP_CR", "25000"))
UNIVERSE_VALIDATE_ON_START       = os.getenv("UNIVERSE_VALIDATE_ON_START", "True").strip().lower() in ("true", "1", "yes")
STARTUP_ANALYSIS_ON_LAUNCH       = os.getenv("STARTUP_ANALYSIS_ON_LAUNCH", "True").strip().lower() in ("true", "1", "yes")
UNIVERSE_VALIDATION_BATCH_SIZE   = int(os.getenv("UNIVERSE_VALIDATION_BATCH_SIZE", "200"))
UNIVERSE_VALIDATION_LOOKBACK_DAYS = int(os.getenv("UNIVERSE_VALIDATION_LOOKBACK_DAYS", "5"))
BSE_UNIVERSE_ENABLED             = os.getenv("BSE_UNIVERSE_ENABLED", "False").strip().lower() in ("true", "1", "yes")

# Large-cap exclude list: Nifty 50 and mega-caps (low intraday beta <1.5%, exclude from explosive picks)
LARGECAP_EXCLUDE_LIST = {
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "SBIN",
    "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
    "SUNPHARMA", "TITAN", "BAJFINANCE", "ULTRACEMCO", "WIPRO", "NESTLEIND",
    "HCLTECH", "POWERGRID", "NTPC", "TECHM", "JSWSTEEL", "TATASTEEL", "ONGC",
    "TATAMOTORS", "BAJAJFINSV", "ADANIENT", "ADANIPORTS", "COALINDIA", "DIVISLAB",
    "DRREDDY", "EICHERMOT", "GRASIM", "HDFCLIFE", "INDUSINDBK", "M&M", "SBILIFE",
    "APOLLOHOSP", "BAJAJ-AUTO", "BPCL", "CIPLA", "BRITANNIA", "HEROMOTOCO",
    "HINDALCO", "LTIM", "TATACONSUM", "SHREECEM", "PIDILITIND", "SIEMENS",
    "ADANIGREEN", "ADANIWILMAR", "AMBUJACEM", "BANKBARODA", "BERGEPAINT",
    "BOSCHLTD", "CANBK", "COLPAL", "DABUR", "DLF", "GAIL", "GODREJCP",
    "HAVELLS", "ICICIPRULI", "IOC", "IRCTC", "JINDALSTEL", "MARICO", "NAUKRI",
    "PNB", "SRF", "TVSMOTOR", "VEDL", "ZOMATO", "ABB", "HAL", "BEL",
    "TRENT", "CHOLAFIN", "VBL", "LICI", "JIOFIN", "INDHOTEL", "MOTHERSON"
}

# ── Intraday Market Periods & Return Targeting ────────────────────────────────
INTRADAY_TARGET_RETURN_MIN_PCT   = float(os.getenv("INTRADAY_TARGET_RETURN_MIN_PCT", "5.0"))
INTRADAY_TARGET_RETURN_MAX_PCT   = float(os.getenv("INTRADAY_TARGET_RETURN_MAX_PCT", "8.0"))
INTRADAY_PERIOD_MORNING          = "09:15-10:15"  # Opening range breakout & vol surge (2.5x)
INTRADAY_PERIOD_MIDDAY           = "10:15-12:30"  # VWAP pullbacks & flag continuations
INTRADAY_PERIOD_AFTERNOON        = "12:30-14:15"  # Afternoon acceleration & day-high breaks

DRY_RUN = os.getenv("DRY_RUN", "False").strip().lower() in ("true", "1", "yes")

# Intraday Pattern Agent
INTRADAY_PATTERN_AGENT_ENABLED = os.getenv("INTRADAY_PATTERN_AGENT_ENABLED", "True").strip().lower() in ("true", "1", "yes")
INTRADAY_PATTERN_SCAN_INTERVAL_MINUTES = int(os.getenv("INTRADAY_PATTERN_SCAN_INTERVAL_MINUTES", "5"))
INTRADAY_PATTERN_MAX_SYMBOLS_PER_CYCLE = int(os.getenv("INTRADAY_PATTERN_MAX_SYMBOLS_PER_CYCLE", "450"))
PATTERN_ROTATING_BATCH_SIZE = int(os.getenv("PATTERN_ROTATING_BATCH_SIZE", str(INTRADAY_PATTERN_MAX_SYMBOLS_PER_CYCLE)))
INTRADAY_PATTERN_MIN_ALERT_SCORE = int(os.getenv("INTRADAY_PATTERN_MIN_ALERT_SCORE", "60"))
INTRADAY_PATTERN_MIN_MOVER_PCT = float(os.getenv("INTRADAY_PATTERN_MIN_MOVER_PCT", "7.0"))
INTRADAY_PATTERN_MARKET_CAP_MAX_CR = float(os.getenv("INTRADAY_PATTERN_MARKET_CAP_MAX_CR", "5000"))
INTRADAY_PATTERN_LOW_LIQUIDITY_MAX_INR = float(os.getenv("INTRADAY_PATTERN_LOW_LIQUIDITY_MAX_INR", "50000000"))

# Grok Dashboard Agent
GROK_DASHBOARD_AGENT_ENABLED = os.getenv("GROK_DASHBOARD_AGENT_ENABLED", "True").strip().lower() in ("true", "1", "yes")
GROK_DASHBOARD_AGENT_INTERVAL_MINUTES = int(os.getenv("GROK_DASHBOARD_AGENT_INTERVAL_MINUTES", "15"))
GROK_DASHBOARD_AGENT_AI_INTERVAL_MINUTES = int(os.getenv("GROK_DASHBOARD_AGENT_AI_INTERVAL_MINUTES", "45"))

# Ollama Intraday Return Agent
OLLAMA_AGENT_ENABLED = os.getenv("OLLAMA_AGENT_ENABLED", "True").strip().lower() in ("true", "1", "yes")
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://127.0.0.1:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_AGENT_INTERVAL_MINUTES = int(os.getenv("OLLAMA_AGENT_INTERVAL_MINUTES", "20"))
OLLAMA_AGENT_CHUNK_SIZE = int(os.getenv("OLLAMA_AGENT_CHUNK_SIZE", "80"))
OLLAMA_AGENT_MAX_SYMBOLS = int(os.getenv("OLLAMA_AGENT_MAX_SYMBOLS", "0"))
OLLAMA_ROTATING_BATCH_SIZE = int(os.getenv("OLLAMA_ROTATING_BATCH_SIZE", "320"))
OLLAMA_AGENT_MIN_RETURN_PCT = float(os.getenv("OLLAMA_AGENT_MIN_RETURN_PCT", "7.0"))
OLLAMA_AGENT_TOP_CANDIDATES = int(os.getenv("OLLAMA_AGENT_TOP_CANDIDATES", "30"))
OLLAMA_AGENT_NOTIFY_TELEGRAM = os.getenv("OLLAMA_AGENT_NOTIFY_TELEGRAM", "True").strip().lower() in ("true", "1", "yes")
OLLAMA_AGENT_TIMEOUT_SECONDS = int(os.getenv("OLLAMA_AGENT_TIMEOUT_SECONDS", "300"))

# Live DB-backed terminal view
TERMINAL_UPDATER_ENABLED = os.getenv("TERMINAL_UPDATER_ENABLED", "True").strip().lower() in ("true", "1", "yes")
TERMINAL_UPDATER_INTERVAL_SECONDS = int(os.getenv("TERMINAL_UPDATER_INTERVAL_SECONDS", "60"))

# One-command automation supervisor. This catches up missed work after Windows
# sleep/restart so scheduled jobs are not silently skipped.
AUTOMATION_SUPERVISOR_ENABLED = os.getenv("AUTOMATION_SUPERVISOR_ENABLED", "True").strip().lower() in ("true", "1", "yes")
AUTOMATION_SUPERVISOR_INTERVAL_SECONDS = int(os.getenv("AUTOMATION_SUPERVISOR_INTERVAL_SECONDS", "60"))
AUTO_LATE_RECOVERY_ENABLED = os.getenv("AUTO_LATE_RECOVERY_ENABLED", "True").strip().lower() in ("true", "1", "yes")
AUTO_LATE_RECOVERY_END = os.getenv("AUTO_LATE_RECOVERY_END", "14:30")
POSTMARKET_CATCHUP_END = os.getenv("POSTMARKET_CATCHUP_END", "23:59")
POSTMARKET_LIGHT_MAX_SYMBOLS = int(os.getenv("POSTMARKET_LIGHT_MAX_SYMBOLS", "450"))
POSTMARKET_DEEP_TIMEOUT_MINUTES = int(os.getenv("POSTMARKET_DEEP_TIMEOUT_MINUTES", "45"))
POSTMARKET_DEEP_LEARNING_ENABLED = os.getenv("POSTMARKET_DEEP_LEARNING_ENABLED", "True").strip().lower() in ("true", "1", "yes")

# Heavy-job traffic control. Keeps every core agent enabled, but prevents the
# expensive background agents from running over each other.
HEAVY_JOB_LOCK_ENABLED = os.getenv("HEAVY_JOB_LOCK_ENABLED", "True").strip().lower() in ("true", "1", "yes")
MAX_HEAVY_JOBS_AT_ONCE = int(os.getenv("MAX_HEAVY_JOBS_AT_ONCE", "1"))
DASHBOARD_AI_BACKGROUND_ONLY = os.getenv("DASHBOARD_AI_BACKGROUND_ONLY", "True").strip().lower() in ("true", "1", "yes")

# ── Reinforcement Learning Architecture ───────────────────────────────────────
# Tier 1: Contextual Multi-Armed Bandit (LinUCB) for morning 20 -> 5 stock selection
BANDIT_SELECTOR_ENABLED = os.getenv("BANDIT_SELECTOR_ENABLED", "True").strip().lower() in ("true", "1", "yes")
BANDIT_ALPHA = float(os.getenv("BANDIT_ALPHA", "0.25"))
BANDIT_WEIGHTS_FILE = os.getenv("BANDIT_WEIGHTS_FILE", "data/bandit_weights.json")

# Tier 2: PPO Intraday Dynamic Trailing Stop & Exit Manager (5-min market checks)
RL_INTRADAY_MANAGER_ENABLED = os.getenv("RL_INTRADAY_MANAGER_ENABLED", "True").strip().lower() in ("true", "1", "yes")
RL_POLICY_FILE = os.getenv("RL_POLICY_FILE", "data/rl_intraday_policy.json")
RL_BREAKEVEN_TRIGGER_PCT = float(os.getenv("RL_BREAKEVEN_TRIGGER_PCT", "1.5"))
RL_TIGHTEN_TRIGGER_PCT = float(os.getenv("RL_TIGHTEN_TRIGGER_PCT", "2.8"))
RL_TAKE_PROFIT_TRIGGER_PCT = float(os.getenv("RL_TAKE_PROFIT_TRIGGER_PCT", "4.2"))
RL_MAX_SL_PCT = float(os.getenv("RL_MAX_SL_PCT", "2.0"))

