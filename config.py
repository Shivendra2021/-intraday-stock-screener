# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.

import os
from dotenv import load_dotenv

load_dotenv()

# Quant v3: existing/free data only; all execution is simulated research.
QUANT_ENABLED = os.getenv("QUANT_ENABLED", "True").lower() in ("true", "1", "yes")
QUANT_DB_PATH = os.getenv("QUANT_DB_PATH", "data/quant.db")
QUANT_WATCHLIST_TIME = "08:45"
QUANT_CONFIRM_START = "09:30"
QUANT_ENTRY_CUTOFF = "11:00"
QUANT_EXIT_TIME = "15:20"
QUANT_MAX_PICKS = 3
QUANT_WATCHLIST_SIZE = int(os.getenv("QUANT_WATCHLIST_SIZE", "100"))
QUANT_BROAD_BATCH_SIZE = int(os.getenv("QUANT_BROAD_BATCH_SIZE", "100"))
QUANT_MIN_DAILY_VALUE = float(os.getenv("QUANT_MIN_DAILY_VALUE", "20000000"))
QUANT_MIN_PRICE = 20.0
QUANT_MAX_STOP_PCT = 3.0
QUANT_MIN_STOP_PCT = 0.5
QUANT_MAX_SPREAD_PCT = 0.30
QUANT_QUOTE_MAX_AGE_SECONDS = 90
QUANT_BAR_MAX_AGE_SECONDS = 120
QUANT_MIN_CIRCUIT_HEADROOM_PCT = float(os.getenv("QUANT_MIN_CIRCUIT_HEADROOM_PCT", "2.0"))
AI_DYNAMIC_SL_ENABLED = True
QUANT_COST_BPS = float(os.getenv("QUANT_COST_BPS", "20"))  # modeled round trip
QUANT_SLIPPAGE_BPS = float(os.getenv("QUANT_SLIPPAGE_BPS", "5"))  # each fill
QUANT_MIN_P7 = float(os.getenv("QUANT_MIN_P7", "0.30"))
QUANT_MIN_MODEL_DAYS = int(os.getenv("QUANT_MIN_MODEL_DAYS", "30"))
QUANT_MIN_MODEL_SAMPLES = int(os.getenv("QUANT_MIN_MODEL_SAMPLES", "300"))
QUANT_MIN_EVAL_TRADES = int(os.getenv("QUANT_MIN_EVAL_TRADES", "20"))
QUANT_DATA_TIMEOUT_SECONDS = 12
QUANT_RESEARCH_BUDGET_SECONDS = 900
QUANT_PREPARE_BUDGET_SECONDS = 45
QUANT_HISTORY_DAYS = 59  # free 5-minute history; provider coverage is audited
QUANT_MODEL_MAX_AGE_DAYS = 30
QUANT_DASHBOARD_HOST = os.getenv("QUANT_DASHBOARD_HOST", "127.0.0.1")
QUANT_AI_DAILY_REVIEW_ENABLED = os.getenv("QUANT_AI_DAILY_REVIEW_ENABLED", "True").strip().lower() in ("true", "1", "yes")
QUANT_AI_MAX_DAILY_CALLS = 1
QUANT_BACKFILL_TARGET_SESSIONS = int(os.getenv("QUANT_BACKFILL_TARGET_SESSIONS", "40"))
QUANT_FORWARD_MIN_DAYS = int(os.getenv("QUANT_FORWARD_MIN_DAYS", "5"))

# Angel One SmartAPI is used only for read-only market data. No order endpoint is
# implemented by Quant V3.
ANGEL_ENABLED = os.getenv("ANGEL_ENABLED", "True").strip().lower() in ("true", "1", "yes")
ANGEL_API_KEY = os.getenv("ANGEL_API_KEY", "")
ANGEL_CLIENT_CODE = os.getenv("ANGEL_CLIENT_CODE", "")
ANGEL_PIN = os.getenv("ANGEL_PIN", "")
ANGEL_TOTP_SECRET = os.getenv("ANGEL_TOTP_SECRET", "")
ANGEL_BASE_URL = os.getenv("ANGEL_BASE_URL", "https://apiconnect.angelone.in")
ANGEL_INSTRUMENT_MASTER_URL = os.getenv("ANGEL_INSTRUMENT_MASTER_URL", "https://margincalculator.angelbroking.com/OpenAPI_File/files/OpenAPIScripMaster.json")
ANGEL_QUOTE_TIMEOUT_SECONDS = int(os.getenv("ANGEL_QUOTE_TIMEOUT_SECONDS", "8"))
ANGEL_HISTORY_BATCH_DAYS = int(os.getenv("ANGEL_HISTORY_BATCH_DAYS", "30"))

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

# ── Pick Selection & AI Dynamic Risk ──────────────────────────────────────────
TOP_N_PICKS              = 3
MIN_SCORE_THRESHOLD      = 55
MIN_TARGET_MOVE_PCT      = 4.0
MAX_TARGET_MOVE_PCT      = 10.0
SL_ATR_MULTIPLIER        = 1.5
MAX_SL_PCT               = 3.0
MIN_RISK_REWARD          = 2.0
AI_DYNAMIC_SL_ENABLED    = True

# ── Filters (Aligned across engines) ──────────────────────────────────────────
MIN_VOLUME_FILTER        = 50_000
MIN_PRICE_FILTER         = 20.0

# ── Paths ──────────────────────────────────────────────────────────────────────
DB_PATH                  = "data/history.db"
DAILY_PICKS_JSON_PATH    = "data/daily_picks_history.json"
LOG_PATH                 = "logs/bot.log"
OUTPUT_DIR               = "output/"

# # ── Telegram ───────────────────────────────────────────────────────────────────
TELEGRAM_BOT_TOKEN       = os.getenv("TELEGRAM_BOT_TOKEN", os.getenv("TELEGRAM_TOKEN", ""))
TELEGRAM_TOKEN           = os.getenv("TELEGRAM_TOKEN", TELEGRAM_BOT_TOKEN)
TELEGRAM_CHAT_ID         = os.getenv("TELEGRAM_CHAT_ID", "")

# ── Optional Broker ────────────────────────────────────────────────────────────
DHAN_CLIENT_ID           = os.getenv("DHAN_CLIENT_ID", "")
DHAN_ACCESS_TOKEN        = os.getenv("DHAN_ACCESS_TOKEN", "")
JUGAAD_DATA_ENABLED      = os.getenv("JUGAAD_DATA_ENABLED", "True").strip().lower() in ("true", "1", "yes")
ZERODHA_API_KEY          = os.getenv("ZERODHA_API_KEY", "")
ZERODHA_ACCESS_TOKEN     = os.getenv("ZERODHA_ACCESS_TOKEN", "")

# ── Google Gemini AI Engine (Trading Quant V4) ──────────────────────────────────
GEMINI_API_KEY           = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL             = os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
GEMINI_PROJECT_NAME      = os.getenv("GEMINI_PROJECT_NAME", "projects/460086929922")
GEMINI_PROJECT_NUMBER    = os.getenv("GEMINI_PROJECT_NUMBER", "460086929922")
GEMINI_AGENT_ENABLED     = os.getenv("GEMINI_AGENT_ENABLED", "True").strip().lower() in ("true", "1", "yes")

# ── Mistral AI Intelligence ────────────────────────────────────────────────────
MISTRAL_API_KEY          = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODEL            = os.getenv("MISTRAL_MODEL", "open-mistral-7b")
MISTRAL_BASE_URL         = os.getenv("MISTRAL_BASE_URL", "https://api.mistral.ai/v1/chat/completions")

# ── OpenRouter Multi-Model Gateway ─────────────────────────────────────────────
OPENROUTER_API_KEY       = os.getenv("OPENROUTER_API_KEY", os.getenv("OPENROUTER_GEMMA_KEY", "")).strip()
OPENROUTER_BASE_URL      = os.getenv("OPENROUTER_BASE_URL", "https://openrouter.ai/api/v1/chat/completions")
OPENROUTER_MODEL         = os.getenv("OPENROUTER_MODEL", "meta-llama/llama-3.3-70b-instruct:free")
OPENROUTER_ENABLED       = os.getenv("OPENROUTER_ENABLED", "True").strip().lower() in ("true", "1", "yes")

# Legacy Grok/xAI compatibility (decommissioned per user instruction)
GROK_API_KEY             = ""
XAI_API_KEY              = ""
XAI_MODEL                = ""
XAI_BASE_URL             = ""
XAI_BRAIN_ENABLED        = False
XAI_BRAIN_REVIEW_ALERTS  = False
XAI_BRAIN_TIMEOUT_SECONDS = 60
XAI_BRAIN_MIN_INTERVAL_SECONDS = 0
XAI_BRAIN_MAX_DAILY_CALLS = 200

# ── AI reviewers — Qwen Max primary, OpenRouter Gemma challenger ──────────────
DASHSCOPE_API_KEY        = os.getenv("DASHSCOPE_API_KEY", "")
DASHSCOPE_BASE_URL       = os.getenv("DASHSCOPE_BASE_URL", "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions")
QWEN_MAX_MODEL           = os.getenv("QWEN_MAX_MODEL", "qwen3.7-max")
OPENROUTER_GEMMA_KEY     = os.getenv("OPENROUTER_GEMMA_KEY", OPENROUTER_API_KEY)
OPENROUTER_GEMMA_MODEL   = os.getenv("OPENROUTER_GEMMA_MODEL", "google/gemma-4-26b-a4b-it:free")
OPENROUTER_FREE_FALLBACK_MODELS = tuple(
    model.strip() for model in os.getenv(
        "OPENROUTER_FREE_FALLBACK_MODELS",
        "google/gemma-4-31b-it:free,qwen/qwen3.8-27b:free,nvidia/nemotron-3.5-lightning:free",
    ).split(",") if model.strip()
)
HF_TOKEN                 = os.getenv("HF_TOKEN", "")
HF_ROUTER_URL            = os.getenv("HF_ROUTER_URL", "https://router.huggingface.co/v1")
HF_DAILY_LEARNING_ENABLED = False  # retained only for reading historical status

# Legacy provider settings are retained only to read previous reports.
OPENROUTER_GROK_KEY      = ""
OPENROUTER_GPT_KEY       = ""
GROK_MODEL               = ""
GPT_MODEL                = os.getenv("GPT_MODEL", "openai/gpt-4o")

# Groq API (not Grok/xAI). Used as a controlled DeepSeek-R1 reasoning fallback
# for dashboard reviews and after-market learning, not for every scan cycle.
GROQ_API_KEY             = os.getenv("GROQ_API_KEY", "")
GROQ_BASE_URL            = os.getenv("GROQ_BASE_URL", "https://api.groq.com/openai/v1/chat/completions")
GROQ_DEEPSEEK_MODEL      = os.getenv("GROQ_DEEPSEEK_MODEL", "qwen/qwen3.6-27b")
GROQ_DEEPSEEK_ENABLED    = os.getenv("GROQ_DEEPSEEK_ENABLED", "False").strip().lower() in ("true", "1", "yes")
GROQ_DEEPSEEK_TIMEOUT_SECONDS = int(os.getenv("GROQ_DEEPSEEK_TIMEOUT_SECONDS", "60"))

# ── News APIs & Real-Time Catalyst Search ────────────────────────────────────
NEWSAPI_KEY              = os.getenv("NEWSAPI_KEY", "")
THENEWSAPI_KEY           = os.getenv("THENEWSAPI_KEY", "")
SERPAPI_KEY              = os.getenv("SERPAPI_KEY", "199deab6a92c965bbcc4d2cf6378ac886d7502cc7154794ff182ee4712e98202")
TAVILY_API_KEY           = os.getenv("TAVILY_API_KEY", "")
FINNHUB_API_KEY          = os.getenv("FINNHUB_API_KEY", "dajfrqhr01qhhp590rc0dajfrqhr01qhhp590rcg")
FINNHUB_ENABLED          = os.getenv("FINNHUB_ENABLED", "True").strip().lower() in ("true", "1", "yes")
FRED_API_KEY             = os.getenv("FRED_API_KEY", "ccdfbb7fc946c952a51347bbdde32eda")
FRED_ENABLED             = os.getenv("FRED_ENABLED", "True").strip().lower() in ("true", "1", "yes")
TWELVE_DATA_API_KEY      = os.getenv("TWELVE_DATA_API_KEY", "34a6780e5c914f14b929067ca8d4cb92")
TWELVE_DATA_ENABLED      = os.getenv("TWELVE_DATA_ENABLED", "True").strip().lower() in ("true", "1", "yes")
CATALYST_SEARCH_ENABLED  = os.getenv("CATALYST_SEARCH_ENABLED", "True").strip().lower() in ("true", "1", "yes")
CATALYST_MAX_DAILY_SEARCHES = int(os.getenv("CATALYST_MAX_DAILY_SEARCHES", "8"))

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
GROK_DASHBOARD_AGENT_ENABLED = os.getenv("GROK_DASHBOARD_AGENT_ENABLED", "False").strip().lower() in ("true", "1", "yes")
GROK_DASHBOARD_AGENT_INTERVAL_MINUTES = int(os.getenv("GROK_DASHBOARD_AGENT_INTERVAL_MINUTES", "15"))
GROK_DASHBOARD_AGENT_AI_INTERVAL_MINUTES = int(os.getenv("GROK_DASHBOARD_AGENT_AI_INTERVAL_MINUTES", "45"))

# Ollama Intraday Return Agent
OLLAMA_AGENT_ENABLED = os.getenv("OLLAMA_AGENT_ENABLED", "False").strip().lower() in ("true", "1", "yes")
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
GROK_DASHBOARD_AGENT_INTERVAL_MINUTES = int(os.getenv("GROK_DASHBOARD_AGENT_INTERVAL_MINUTES", "15"))
GROK_DASHBOARD_AGENT_AI_INTERVAL_MINUTES = int(os.getenv("GROK_DASHBOARD_AGENT_AI_INTERVAL_MINUTES", "45"))

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

# ── Ollama Intraday Agent ─────────────────────────────────────────────────────
OLLAMA_AGENT_ENABLED = os.getenv("OLLAMA_AGENT_ENABLED", "False").strip().lower() in ("true", "1", "yes")
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
RL_MAX_SL_PCT = float(os.getenv("RL_MAX_SL_PCT", "3.0"))

# ── Institutional Quant & Risk Engine (MT5 Hedge Terminal Port) ───────────────
RVOL_THRESHOLD_BREAKOUT = float(os.getenv("RVOL_THRESHOLD_BREAKOUT", "1.8"))
RVOL_BULL_TRAP_THRESHOLD = float(os.getenv("RVOL_BULL_TRAP_THRESHOLD", "1.0"))
ATR_MAX_EXPANSION_PCT = float(os.getenv("ATR_MAX_EXPANSION_PCT", "90.0"))
ATR_PRIME_EXPANSION_PCT = float(os.getenv("ATR_PRIME_EXPANSION_PCT", "40.0"))
MAX_BID_ASK_SPREAD_PCT = float(os.getenv("MAX_BID_ASK_SPREAD_PCT", "0.05"))
AUDIT_RULES_PATH = os.getenv("AUDIT_RULES_PATH", "data/audit_rules.json")
EARNINGS_FREEZE_SYMBOLS = [s.strip().upper() for s in os.getenv("EARNINGS_FREEZE_SYMBOLS", "").split(",") if s.strip()]
MACRO_EVENTS_TODAY = []  # Can be configured with high-impact events: [{"name": "RBI Policy", "time": "10:00"}]

# ── Daily Loss Circuit Breaker (Tilt Protection) ──────────────────────────────
MAX_DAILY_SL_HITS = int(os.getenv("MAX_DAILY_SL_HITS", "2"))
MAX_DAILY_PORTFOLIO_LOSS_PCT = float(os.getenv("MAX_DAILY_PORTFOLIO_LOSS_PCT", "2.0"))

# ── 2-Stage Runner Target Engine (+7% to +10% Criteria) ────────────────────────
RUNNER_BREAKEVEN_PCT = float(os.getenv("RUNNER_BREAKEVEN_PCT", "3.5"))
RUNNER_TP1_PCT = float(os.getenv("RUNNER_TP1_PCT", "7.0"))
RUNNER_TP2_PCT = float(os.getenv("RUNNER_TP2_PCT", "10.2"))
RUNNER_TRAIL_LOCKED_PCT = float(os.getenv("RUNNER_TRAIL_LOCKED_PCT", "3.5"))
