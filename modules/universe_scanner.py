# MarketMind Pro — Research and Advisory Only
# This system does NOT place trades. All picks are for research purposes.
# Past pattern performance does not guarantee future returns.
# All trading decisions are the user's own responsibility.

"""
universe_scanner.py — Full NSE Universe Morning Scanner

Scans entire NSE universe (~2000 stocks) with parallel workers.
Time budget: 40 minutes max.

Workflow:
1. Load full universe
2. Partition into 16 batches (~125 stocks each)
3. Parallel fetch + quick analysis
4. Rank by composite score
5. Return Top 20 for next stage
"""

from __future__ import annotations
import logging
import multiprocessing as mp
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from typing import Any

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Configuration
MIN_PRICE_FILTER = 50
MIN_VOLUME_FILTER = 50_000
MIN_PRICE_CHANGE_PCT = -5.0  # Allow some downside, will filter later
MAX_PRICE_CHANGE_PCT = 15.0
TOP_N_RESULTS = 20
WORKER_COUNT = 16
LAST_SCAN_DIAGNOSTICS: dict[str, Any] = {}


def _quick_analyze_symbol(symbol: str) -> dict[str, Any] | None:
    result, _reason = _quick_analyze_symbol_with_reason(symbol)
    return result


def _quick_analyze_symbol_with_reason(symbol: str) -> tuple[dict[str, Any] | None, str]:
    """
    Quick analysis of a single symbol.
    Runs in worker process - must be module-level function.
    """
    try:
        from modules.fetch import fetch_ohlcv
        from modules.scanner import _get_nse_symbol
        
        # Ensure .NS suffix
        nse_sym = _get_nse_symbol(symbol)
        if not nse_sym:
            return None, "no_nse_symbol"
        
        # Fetch 5-day data
        df = fetch_ohlcv(nse_sym, period="5d")
        if df is None or df.empty or len(df) < 2:
            return None, "no_data"
        
        close_prices = df["close"].astype(float)
        volume = df["volume"].astype(float)
        
        current_price = float(close_prices.iloc[-1])
        price_5d_ago = float(close_prices.iloc[0])
        
        # Quick filters
        if current_price < MIN_PRICE_FILTER:
            return None, "price_below_filter"
        
        avg_volume = volume.mean()
        if avg_volume < MIN_VOLUME_FILTER:
            return None, "volume_below_filter"
        
        # Calculate metrics
        price_change_pct = ((current_price - price_5d_ago) / price_5d_ago) * 100
        
        # Volume ratio vs 5-day average
        vol_ratio = float(volume.iloc[-1] / avg_volume) if avg_volume > 0 else 1.0
        
        # Gap up from previous close
        if len(df) >= 2:
            prev_close = float(df["close"].iloc[-2])
            gap_up = ((current_price - prev_close) / prev_close) * 100
        else:
            gap_up = 0.0
        
        # Quick RSI (simplified)
        delta = close_prices.diff()
        gain = delta.clip(lower=0).mean()
        loss = (-delta.clip(upper=0)).mean()
        rs = gain / loss if loss > 0 else 1.0
        rsi = 100 - (100 / (1 + rs))
        
        # Composite score (quick version)
        score = (
            (min(max(rsi, 30), 70) / 10) * 2 +  # RSI component
            min(vol_ratio, 3) * 3 +  # Volume component
            min(max(price_change_pct, -3), 8) / 2 +  # Momentum
            min(max(gap_up, 0), 5) * 2  # Gap component
        )
        
        return {
            "symbol": symbol.replace(".NS", ""),
            "price": current_price,
            "price_change_pct": price_change_pct,
            "volume_ratio": vol_ratio,
            "rsi": rsi,
            "gap_up": gap_up,
            "avg_volume": avg_volume,
            "score": score,
        }, "passed"
        
    except Exception:
        return None, "error"


def _batch_analyze(symbols: list[str]) -> dict[str, Any]:
    """Analyze a batch of symbols."""
    results = []
    stats: dict[str, int] = {
        "symbols": len(symbols),
        "passed": 0,
        "no_nse_symbol": 0,
        "no_data": 0,
        "price_below_filter": 0,
        "volume_below_filter": 0,
        "error": 0,
    }
    for sym in symbols:
        result, reason = _quick_analyze_symbol_with_reason(sym)
        stats[reason] = stats.get(reason, 0) + 1
        if result:
            results.append(result)
    return {"results": results, "stats": stats}


def get_last_scan_diagnostics() -> dict[str, Any]:
    """Return summary of the most recent universe scan in this process."""
    return dict(LAST_SCAN_DIAGNOSTICS)


def get_full_universe() -> list[str]:
    """Load full NSE universe for scanning."""
    try:
        from modules.scanner import get_universe
        universe = get_universe()
        if universe:
            return universe
    except Exception:
        pass
    
    # Fallback: Nifty500 + Extended
    return _EXTENDED_UNIVERSE


_EXTENDED_UNIVERSE = [
    "RELIANCE", "TCS", "HDFCBANK", "INFY", "ICICIBANK", "HINDUNILVR", "SBIN",
    "BHARTIARTL", "ITC", "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI",
    "SUNPHARMA", "TITAN", "BAJFINANCE", "ULTRACEMCO", "WIPRO", "NESTLEIND",
    "HCLTECH", "POWERGRID", "NTPC", "TECHM", "JSWSTEEL", "TATASTEEL", "ONGC",
    "TATAMOTORS", "BAJAJFINSV", "ADANIENT", "ADANIPORTS", "COALINDIA", "DIVISLAB",
    "DRREDDY", "EICHERMOT", "GRASIM", "HDFCLIFE", "INDUSINDBK", "M&M", "SBILIFE",
    "APOLLOHOSP", "BAJAJ-AUTO", "BPCL", "CIPLA", "BRITANNIA", "HEROMOTOCO",
    "HINDALCO", "LTIM", "TATACONSUM", "UPL", "VEDL", "SHREECEM", "PIDILITIND",
    "SIEMENS", "ADANIGREEN", "ADANIWILMAR", "AMBUJACEM", "AUROPHARMA", "BANKBARODA",
    "BERGEPAINT", "BIOCON", "BOSCHLTD", "CANBK", "CHOLAFIN", "COLPAL", "CONCOR",
    "CUMMINSIND", "DABUR", "DLF", "ESCORTS", "FEDERALBNK", "FORTIS", "GAIL",
    "GLAXO", "GODREJCP", "GODREJPROP", "HAVELLS", "ICICIPRULI", "IDFCFIRSTB",
    "INDHOTEL", "INDUSTOWER", "IOC", "IRCTC", "JINDALSTEL", "JUBLFOOD",
    "LICHSGFIN", "LUPIN", "MCDOWELL-N", "MFSL", "MOTHERSON", "MPHASIS", "MRF",
    "MUTHOOTFIN", "NAUKRI", "NMDC", "PAGEIND", "PEL", "PERSISTENT", "PETRONET",
    "PFC", "PIIND", "PNB", "POLYCAB", "PVRINOX", "RAMCOCEM", "RECLTD", "SAIL",
    "SBICARD", "SRF", "STARHEALTH", "SUNTV", "TORNTPHARM", "TORNTPOWER", "TVSMOTOR",
    "UBL", "UNIONBANK", "VOLTAS", "WHIRLPOOL", "ZEEL", "ZOMATO", "NYKAA",
    "PAYTM", "MARICO", "ALKEM", "ABBOTINDIA", "ACC", "AARTIIND", "AAVAS",
    "ADANIENT", "ADANIPORTS", "ADANIGREEN", "ADANIWEL", "ADANIPOWER",
    "AEGISLOG", "AGI", "AGROPHARMA", "AHF", "AIRL", "AJANTAPHARM",
    "AKZOINDIA", "ALAL", "ALKYLAM", "ALLCARGO", "ALM", "ALOKAB", "AMARAJBA",
    "AMBUJASL", "AMRUTAN", "ANAB", "ANDHRAUP", "ANM", "ANS", "ANT",
    "APARIN", "APC", "APLAPOLLO", "APOLLODY", "APOLLOTRI", "ARCEEDU",
    "ARVIND", "ARVINDFAS", "ASAHIIND", "ASHLOK", "ASHOK", "ASHOKLEY",
    "ASTRAL", "ATFL", "ATUL", "AUBANK", "AUTOLINE", "AVANTIFE",
    "AXISBANK", "BAJAJCON", "BAJAJELEC", "BAJAJFINSV", "BAJAJHFC",
    "BAJPAIS", "BALAJI", "BALAMAT", "BALKRISHNA", "BALLARPUR",
    "BALMLAW", "BALPHARMA", "BANDHANBK", "BANKINDIA", "BARODYA",
    "BASF", "BASML", "BATAINDIA", "BAYERCROP", "BBL", "BBOX",
    "BDL", "BEC", "BEL", "BFUTILIT", "BGRENERGY", "BHARATFIN",
    "BHARATFORG", "BHARATGRF", "BHARTI", "BHEL", "BHFTI", "BHPOWER",
    "BIOCON", "BIRLACORP", "BLUETICK", "BLV", "BNG", "BOB", "BPCL",
    "BPL", "BRFL", "BRITANNIA", "BROOKS", "BSEL", "BSHSIG4",
    "BTML", "BTR", "BUTANI", "BVCL", "BYD", "CADILAHC", "CAMP",
    "CANBK", "CANFINHOME", "CAPL", "CASTROL", "CEATLTD", "CEBBCO",
    "CEL", "CENTRALBK", "CENTUM", "CENTURYPLY", "CERA", "CESC",
    "CGCL", "CHAMPS", "CHEMFAB", "CHENNAIPET", "CHOLAFIN", "CIBAN30",
    "CIMMCO", "CLNINDIA", "CLPR", "CMI", "COALINDIA", "COASTAL",
    "COFORGE", "COLPAL", "COMP", "CONCOR", "COROMANDEL", "COSMOFILMS",
    "COXINGS", "CREATIVE", "CRISIL", "CRODA", "CUB", "CUMMINSIND",
    "DAAWAT", "DABUR", "DALMIAS", "DALMIAB", "DEEPAKF", "DEEPAKNTR",
    "DELTACORP", "DELTAMAG", "DEN", "DENORA", "DHAMPUR", "DHANBANK",
    "DHFL", "DIAMONDS", "DICIND", "DISHTV", "DIVISLAB", "DIXON",
    "DLINKINDIA", "DLM", "DMART", "DNOW", "DONEAR", "DPSCLTD",
    "DQE", "DREDY", "DRL", "DRREDDY", "DRSD", "DTML", "DUNCAN",
    "DWARKES", "DYNAMAT", "EASTSILK", "EKC", "ELAND", "ELECTCAST",
    "ELGIRUBCO", "EMKAY", "EMKAY GLOBAL", "ENDURANCE", "ENERGY", "ENGINERS",
    "EPL", "EPOXY", "EQUITAS", "ERIS", "EROSMEDIA", "ESAB",
    "ESCORTS", "ESSELPACK", "ETHOS", "EVEREADY", "EXIDE", "FCL",
    "FEDERALBNK", "FELDYN", "FIEM", "FINEORG", "FINOPB", "FIVESTAR",
    "FLEXIT", "FLUORO", "FORBES", "FORCEMOT", "FORTIS", "FOSSTEJS",
    "FOURTHDIM", "FRETAIL", "GAIL", "GAMMNINFRA", "GANESHHOUC", "GANGAPAPER",
    "GARDENRE", "GARGFIB", "GATEWAY", "GCP", "GEECEE", "GENCON",
    "GENESYS", "GENM", "GENUS", "GESHIP", "GICL", "GICRE",
    "GILLANDERS", "GLAXO", "GLOBAL", "GLOBALLOG", "GLOBLTD",
    "GLOCR", "GLORY", "GLS", "GMDCLTD", "GMIFA", "GMRINFRA",
    "GNA", "GNFC", "GOAC", "GODFRY", "GODREJ", "GODREJAGAR",
    "GODREJCP", "GODREJIND", "GODREJPROP", "GODREJVAS", "GPIL",
    "GPPL", "GRAVITA", "GRBL", "GREENLAM", "GREENPANEL", "GREENPLY",
    "GREESC", "GRINDWELL", "GROW", "GSFC", "GSKCONS", "GSPL",
    "GUJALKALI", "GUJPETRO", "GULF", "GULFOIL", "GVC", "HAL",
    "HAVELLS", "HAVISHA", "HBLPOWER", "HCLTECH", "HDFC", "HDFCAMC",
    "HDFCBANK", "HDFCLIFE", "HDFCSEC", "HDIL", "HEADG", "HEG",
    "HELAPP", "HERO", "HESTC", "HFCL", "HINDALCO", "HINDBET",
    "HINDCOPPER", "HINDDOR", "HINDFOODS", "HINDMERC", "HINDMOTORS",
    "HINDOIL", "HINDPETRO", "HINDSYNT", "HINDUNILVR", "HINDZINC",
    "HISARMETAL", "HITECH", "HITECHPL", "HLEGLAS", "HLVL", "HMT",
    "HOMEFIRST", "HONASA", "HONAUT", "HONDAPOWER", "HOTELF", "HPL",
    "HSCL", "HSIL", "HTMEDIA", "HUDCO", "IBULHSGFIN", "ICICI", "ICICIBANK",
    "ICICIGI", "ICICIPRULI", "ICICISE", "IDBI", "IDCIBANK", "IDEA",
    "IDFC", "IDFCTB", "IFB", "IFCI", "IGL", "IIFL", "IIHL",
    "INDUSINDBK", "INDUSTOWER", "INFY", "INGV", "INNO", "INTELLECT",
    "INTLOANS", "IOB", "IOC", "IOCON", "IPAPL", "IRB", "IRCON",
    "IRCTC", "ISEC", "ISG", "ITC", "ITDC", "ITECHEXP",
    "ITI", "IVC", "IWP", "IXIGO", "JAGRAN", "JAIC", "JAM",
    "JAYAGRO", "JAYBARM", "JAYCH", "JAYIN", "JBCH", "JBF",
    "JCBL", "JCHM", "JEKPL", "JELDYNE", "JHS", "JINDALPOLY",
    "JINDALSAW", "JINDALSTEL", "JIOFIN", "JKCEMENT", "JKIL",
    "JKLAKSHMI", "JKPAPER", "JKTYRE", "JMA", "JMFIN", "JMCCUK",
    "JME", "JMFIN", "JMGCORP", "JSWENERGY", "JSWHL", "JSWISPL",
    "JSWSTEEL", "JTL", "JUBL", "JUBLFOOD", "JUBLIN", "JUN",
    "JUSTDIAL", "JVLAGRO", "JYOTHYLAB", "JYOTISTRUC", "K&R",
    "KAJARI", "KALPAT", "KALYANI", "KAMDHENU", "KANANI", "KANPRPLA",
    "KAPSTON", "KARRO", "KARURVYSYA", "KAJARIA", "KAYNES", "KCD",
    "KEI", "KELLTONT", "KERNEL", "KFA", "KGDCL", "KGL",
    "KHARIDHAR", "KHY", "KINGFA", "KIRLOSCARS", "KIRLOSKAR",
    "KLKENSO", "KNRCON", "KNTM", "KOHINOOR", "KOTAKBANK", "KPIL",
    "KPRMILL", "KREBSBIO", "KSB", "KSCL", "KSL", "KSREP",
    "KTKBANK", "KUANTUM", "LAHOTI", "LAXMICOT", "LAXMICROW",
    "LGBBROWS", "LGBFORGE", "LIBERTSHOE", "LIC", "LICHSGFIN",
    "LINCOLN", "LIND", "LOVABLE", "LPDC", "LPJ", "LPSC",
    "LSIL", "LT", "LTI", "LTTS", "LUMAX", "LUMAXIND",
    "LUXIND", "LYF", "M&M", "M&MFIN", "MAANALU", "MACPOWER",
    "MADHAV", "MADHURCO", "MADRAS", "MAFANG", "MAGMAPL", "MAHABANK",
    "MAHAPEX", "MAHK", "MAHLOG", "MAHOL", "MAHSE", "MAIAH",
    "MAN50", "MANAKSIA", "MANALU", "MANAPPURAM", "MANBA", "MANCO",
    "MANDITRAD", "MANGCHC", "MANGIF", "MANGTOP", "MANINFRA",
    "MANK", "MANMAN", "MANORM", "MAPMYIND", "MARAL", "MARBURY",
    "MARG", "MARICO", "MARIN", "MARK", "MARKSANS", "MARSHALL",
    "MARUTI", "MAS", "MATRIM", "MAWANCO", "MAXIND", "MAXV",
    "MAYUR", "MBC", "MBL", "MBLINFRA", "MBPJ", "MCCHD",
    "MCLEOD", "MCR", "MEDAN", "MEDCAP", "MEDIATOP", "MEDPLUS",
    "MEGA", "MEGH", "MEL", "MEP", "METROCO", "MFL",
    "MGL", "MGM", "MGN", "MGOLD", "MICRO", "MINAXI",
    "MINDAB", "MINDA", "MINDAP", "MITTAL", "MKCL", "ML",
    "MMNL", "MMT", "MOIL", "MOTILALOFS", "MPL", "MRF",
    "MRPL", "MSL", "MSYL", "MTNL", "MTPL", "MUKANDL",
    "MULLER", "MUL", "MUS", "MUTHOOT", "MUTIN", "MVEND",
    "MVIL", "NACLIND", "NAGARJUNA", "NCL", "NMDC", "NNL",
    "NOESIS", "NRAIL", "NRBBHARAT", "NSEC", "NTPC", "NUCLEUS",
    "NUTAN", "NUVAMA", "NV20", "NVD", "OBCL", "OBORT",
    "OIL", "OLECTRA", "ONGC", "ONMOBILE", "ONWARD",
    "OPTI", "OPTOCircu", "ORBIT", "ORCL", "ORIENT", "ORIENTBELL",
    "ORISMA", "ORN", "OROPE", "ORR", "OSWAL", "OVT",
    "PAAM", "P&NH", "PACIFIC", "PAGEIND", "PAI", "PAKH",
    "PALASHA", "PALCO", "PAR", "PARAB", "PARACABLE", "PARASDEF",
    "PARBER", "PARSHWA", "PARTAN", "PARVATI", "PATAN",
    "PATEL", "PATH", "PATNAM", "PCBL", "PCJEWELLER", "PCOCON",
    "PDD", "PDSL", "PEN", "PENARIA", "PEOPLE", "PERFECT",
    "PERI", "PERSISTENT", "PETE", "PETRONET", "PETRONLPG",
    "PFC", "PFIZER", "PGB", "PGHH", "PGIL", "PGL",
    "PH", "PHL", "PHOENIXL", "PIDILITIND", "PIIND", "PIL",
    "PIRELLI", "PJL", "PKAZI", "PKF", "PKHF", "PLAH",
    "PLAND", "PLASS", "PNB", "PNC", "PNL", "PNRL",
    "POCD", "PODDAR", "POOJA", "PNBH", "PORT", "POWERGRID",
    "POWERINDIA", "POWERM", "PPA", "PPAP", "PPL", "PRA",
    "PRADPM", "PRANAV", "PRATIK", "PRAX", "PREMIER",
    "PRIM", "PRINCEP", "PRINT", "PRISMA", "PRL",
    "PROHOUSE", "PROMACT", "PROND", "PTC", "PULSAM",
    "PUN", "PUNJAB", "PUSIF", "PVNL", "PYRAMID",
    "QUICKHEAL", "RAH", "RAHEJA", "RAIL", "RAILWAY",
    "RAJC", "RAJESHE", "RAJMET", "RAJRATNA", "RAMAPAL",
    "RCF", "RCOM", "REDINGTON", "RELAXO", "RHIM", "RHL",
    "RICO", "RIIL", "RITCO", "RITES", "RNRL", "ROHL",
    "ROML", "RPL", "RPOWER", "RPM", "RRSECURE", "RUBYMILLS",
    "RUCHIRA", "RUPA", "RUSHIL", "SADBHAV", "SAFARI",
    "SAF", "SAGCEM", "SAIL", "SAL", "SALASAR",
    "SAMTEX", "SANDESH", "SANSERA", "SAP", "SARVESHWAR",
    "SATYAM", "SAWARD", "SBBJ", "SBICARD", "SBIN",
    "SBR", "SBT", "SBW", "SCAPDVR", "SCHAND", "SCHNEIDER",
    "SCI", "SCONE", "SEAMEC", "SELAN", "SELF", "SENCO",
    "SEO", "SERV", "SES", "SETCO", "SETF", "SFB",
    "SFFT", "SFIL", "SGL", "SHAHAL", "SHAKTIPUMP",
    "SHALIMAR", "SHALIW", "SHANKARA", "SHANTI", "SHAW",
    "SHCO", "SHEL", "SHIP", "SHIVAMA", "SHK", "SHL",
    "SHOORA", "SHP", "SHRED", "SIEMENS", "SIGMA",
    "SIL", "SILPI", "SINTRA", "SIVAS", "SKFINDIA",
    "SLISL", "SMACK", "SML", "SMG", "SMR", "SNOWMAN",
    "SOBHA", "SOFF", "SOFY", "SOLARA", "SOLID",
    "SOMATEX", "SONAT", "SOTAC", "SPAL", "SPANDANA",
    "SPARC", "SPC", "SPDL", "SPEC", "SPEED", "SPEL",
    "SPL", "SPN", "SPR", "SPRA", "SPRING",
    "SRL", "SRM", "SRNL", "SRPL", "SSB",
    "SSBI", "SSL", "STAN", "STARL", "STEELSTR",
    "STEL", "STER", "STI", "STONE", "STOREONE",
    "SUPRAJ", "SUPREME", "SURAT", "SURYAROS", "SUTFU",
    "SUZLON", "SVAM", "SVARM", "SYNGENE", "TATA",
    "TATAB", "TATASTEEL", "TATAMOTORS", "TATAPOWER", "TATACHEM",
    "TATACOFFEE", "TATACONSUM", "TATAINV", "TATAMETAL", "TATAPREST",
    "TASL", "TBZ", "TCS", "TDPOW", "TECHM", "TEJAS",
    "TEMPO", "TETRA", "TEXIN", "TIDE", "TIGERS",
    "TIL", "TIMET", "TIMKEN", "TIPS", "TIRUMAL",
    "TITAN", "TNP", "TNR", "TOKAI", "TORNTPHARM",
    "TORNTPOWER", "TRAM", "TRC", "TRIVENI", "TRU",
    "TST", "TTKPRESTIG", "TTL", "TTML", "TURTLE",
    "TV18", "TVS", "TVSMOTOR", "TVSSRIC", "TWC",
    "UBLI", "UCL", "UFLEX", "UJI", "UKLEADER",
    "ULTRACEMCO", "UNICHEM", "UNIONC", "UNIONBANK", "UNITECH",
    "UNITY", "URJA", "USHDE", "UTI", "UTIBCM",
    "UTTAM", "VAIBHAV", "VAL", "VALIANT", "VARDHMAN",
    "VASWANI", "VEDL", "VENKEYS", "VENUS", "VERNO",
    "VESUVIUS", "VETO", "VGUARD", "VIA", "VIJAY", "VIJIF",
    "VINDHA", "VINYL", "VIP", "VISION", "VISU", "VIVAN",
    "VIVIEDU", "VL", "VLL", "VMART", "VOLTAMP", "VOLTAS",
    "VRLLOG", "VSTIND", "VTRANS", "WABAG", "WACC",
    "WANA", "WANBURY", "WARDHA", "WEL", "WELCORP",
    "WELENT", "WELSPUN", "WESTC", "WESTL", "WHIRL",
    "WHIRLPOOL", "WIMBI", "WIT", "WONDERLA", "WPC",
    "WRD", "WSI", "WSTCO", "XCH", "XELPMOC",
    "XPRESSPROD", "YATRA", "YESBANK", "YUL", "ZADC",
    "ZEAL", "ZEEL", "ZEND", "ZENITH", "ZENSAR",
    "ZYDUSWELL", "ZYDUS", "SMCGLOBAL", "SHRADHHA", "GLOBALE",
    "SPECIALITY", "RIDDHI", "SHRIRAM", "UNO", "SHEELA",
    "CENTURYAL", "RUBY", "GANGRATNA", "MANORAMA", "KOHINOOR",
    "KCL", "APCL", "ORBITER", "ADLABS", "FONE", "AHL",
    "AHLUWALIA", "ALKAL", "ALL", "ALMARD", "AMBA", "AMBER",
    "ANANDM", "APFM", "APLL", "APLLTD", "ARBC", "ASDC",
    "ATFL", "ATUL", "AVNT", "BALLARPUR", "BCP", "BDL",
    "BFINV", "BGRID", "BHARATW", "BIPL", "BKNAT", "BKRON",
    "BLUESTAR", "BNR", "BOMD", "BOND", "BROAD", "BRT",
    "BSE", "BTW", "CANTROL", "CARBURY", "CC", "CCH", "CDSL",
    "CEASE", "CELG", "CEND", "CHENNAI", "CHRT", "CIAL",
    "CLD", "CLG", "CMNL", "CORW", "COUNCIL", "CPD",
    "CRANE", "CRD", "CRG", "CROL", "CSB", "CSBBANK",
    "CTE", "CTP", "CUR", "CWRU", "CZM", "DAG",
    "DAIHAN", "DBC", "DBRB", "DCB", "DCL", "DCON",
    "DEEPAKNTR", "DEL", "DELC", "DG", "DGW", "DHANBANK",
    "DHRL", "DICL", "DIGIN", "DJN", "DLG", "DLID",
    "DLTH", "DMR", "DNL", "DNT", "DOR", "DPCON",
    "DPR", "DRL", "DRON", "DSL", "DUPONT", "DUS",
    "DWARKESH", "DWL", "DY", "EASEM", "EC", "ECO",
    "EIHOTEL", "EIS", "EL", "ELC", "ELECTROB",
    "ELECTROP", "ELICIT", "ELL", "EM", "EMAM", "EMAMI",
    "EMKAY", "EMSNL", "ENG", "ENR", "EP", "EPC",
    "EPG", "ERA", "EROSMEDIA", "ESL", "ETIL", "EUS",
    "EVER", "EXCOM", "FCL", "FCM", "FIL", "FINC",
    "FIRST", "FK", "FKE", "FLOUR", "FMNL", "FN", "FOL",
    "FOR", "FORBES", "FORC", "FORTUN", "FRAC", "FREE",
    "FUL", "FVC", "G2G", "GAD", "GAL", "GANDM",
    "GAR", "GBC", "GBD", "GBL", "GC", "GCL",
    "GCM", "GCPL", "GCR", "GEPL", "GGT", "GL",
    "GLFL", "GM", "GMG", "GML", "GMP", "GNL",
    "GP", "GPCL", "GPI", "GPL", "GPSL", "GRA",
    "GRAP", "GRD", "GRE", "GRR", "GSC", "GSL",
    "GSM", "GSN", "GSP", "GT", "GTL", "GTPL",
    "GTTL", "GUI", "GVK", "GW", "GWL", "HA",
    "HADC", "HAIL", "HAL", "HAR", "HASTI", "HAV",
    "HBL", "HC", "HCC", "HCL", "HCM", "HCON",
    "HDC", "HEP", "HER", "HI", "HIMAT", "HIND",
    "HL", "HLAND", "HO", "HOC", "HOME", "HPC",
    "HR", "HRG", "HS", "HSL", "HSN", "HT",
    "HUD", "HUR", "HV", "IC", "ICI", "ICL",
    "ICLD", "ICN", "IDEL", "IDV", "IFIN", "IGC",
    "IHB", "IHP", "IIFL", "IIL", "IN", "INL",
    "INOX", "INSL", "INT", "INV", "IO", "IP",
    "IPA", "IPCL", "IPG", "IPL", "IR", "ISB",
    "ISP", "ITC", "ITL", "IZ", "JAD", "JAIP",
    "JAR", "JAY", "JBS", "JC", "JCB", "JE",
    "JEC", "JEN", "JES", "JET", "JFC", "JGI",
    "JGT", "JINDAL", "JIT", "JK", "JKC", "JKH",
    "JL", "JLF", "JM", "JMD", "JME", "JMF",
    "JMT", "JO", "JP", "JPD", "JPG", "JPH",
    "JPS", "JRD", "JRL", "JRS", "JRW", "JS",
    "JSC", "JSH", "JSL", "JSW", "JT", "JTC",
    "JU", "JUST", "JVL", "JVS", "JY", "JYOTI",
    "K2C", "KA", "KALG", "KALM", "KAND", "KARN",
    "KARNG", "KAY", "KC", "KCD", "KCE", "KCL",
    "KCT", "KDD", "KDG", "KEN", "KES", "KFC",
    "KFD", "KFI", "KFR", "KGEN", "KGL", "KIP",
    "KIR", "KL", "KLG", "KLH", "KLJ", "KLK",
    "KLKE", "KLN", "KLPE", "KLR", "KLS", "KLSE",
    "KM", "KMB", "KMC", "KMG", "KMPL", "KMR",
    "KMS", "KNC", "KND", "KNR", "KON", "KP",
    "KPC", "KPEL", "KPF", "KPI", "KPL", "KPR",
    "KPT", "KR", "KRA", "KRC", "KRE", "KRG",
    "KRLSL", "KRR", "KRS", "KRV", "KSB", "KSD",
    "KSCL", "KSDE", "KSE", "KSR", "KST", "KSVB",
    "KT", "KTB", "KTE", "KTG", "KTH", "KTL",
    "KTR", "KTSE", "KTSM", "KTT", "KVA", "KVBL",
    "KWEB", "L&TFH", "LA", "LAB", "LADD", "LAF",
    "LAFAR", "LAG", "LAK", "LAND", "LAO", "LAP",
    "LAYER", "LBA", "LBC", "LBG", "LBR", "LC",
    "LCA", "LCAL", "LCEM", "LCR", "LD", "LDC",
    "LDE", "LDH", "LDPE", "LEA", "LEAP", "LEL",
    "LFC", "LGB", "LGC", "LGD", "LGF", "LGL",
    "LGS", "LHG", "LHL", "LHP", "LHS", "LHV",
    "LIBAS", "LICF", "LICHF", "LIL", "LINC",
    "LISN", "LL", "LLOYD", "LM", "LMB", "LMK",
    "LMP", "LMR", "LNB", "LNC", "LND", "LNG",
    "LNK", "LNR", "LNT", "LOCO", "LOF", "LOG",
    "LPL", "LPP", "LQ", "LR", "LSL", "LSR",
    "LST", "LSW", "LT", "LTD", "LTE", "LTM",
    "LTP", "LTS", "LTT", "LTV", "LUR", "LUX",
    "LVB", "LVD", "LVL", "LW", "LY", "MAARC",
    "MAB", "MAC", "MACK", "MAD", "MAG", "MAH", "MAHD",
    "MAHF", "MAHHL", "MAHS", "MAI", "MAL", "MAM",
    "MAN", "MANE", "MANG", "MANI", "MANID", "MANL",
    "MANT", "MANV", "MAP", "MAQ", "MAR", "MARG",
    "MARKS", "MART", "MAS", "MASCOT", "MAT", "MAU",
    "MAX", "MAY", "MCA", "MCC", "MCG", "MCH",
    "MCLEOD", "MCM", "MCX", "ME", "MEAI", "MED",
    "MEG", "MEGA", "MEI", "MEL", "MERC", "MES",
    "MET", "METG", "MEXP", "MF", "MFA", "MFC",
    "MFG", "MFIL", "MFL", "MGM", "MGT", "MH",
    "MI", "MICR", "MID", "MILL", "MILTF", "MIM",
    "MIN", "MIPC", "MIRR", "MIT", "MITE", "MIVAN",
    "MJ", "MK", "MKE", "MKT", "ML", "MLA",
    "MLBE", "MLG", "MLL", "MLS", "MLY", "MM",
    "MMA", "MMAO", "MMAS", "MMB", "MMC", "MMD",
    "MMG", "MMGY", "MMM", "MMn", "MMRG", "MMR",
    "MMS", "MMTE", "MMTR", "MN", "MNA", "MNC",
    "MNG", "MNO", "MNP", "MNR", "MNS", "MOC",
    "MOD", "MOG", "MOM", "MOO", "MOP", "MORE",
    "MORF", "MORPH", "MOS", "MOSS", "MOW", "MP",
    "MPA", "MPC", "MPE", "MPG", "MPI", "MPL", "MPO",
    "MPR", "MPS", "Mpt", "MR", "MRB", "MRC",
    "MRG", "MRR", "MRS", "MRT", "MRV", "MRZM",
    "MS", "MSA", "MSE", "MSL", "MSM", "MSR",
    "MST", "MSX", "MT", "MTD", "MTG", "MTH",
    "MTL", "MTP", "MTR", "MTS", "MTV", "MTW", "MU",
    "MUN", "MUR", "MUTC", "MUTV", "MV", "MVAL",
    "MW", "MWA", "MX", "MYB", "N", "N.B", "NAK",
    "NAM", "NAND", "NAR", "NAS", "NAT", "NAV",
    "NAVIP", "NB", "NBA", "NBC", "NBOT", "NBP",
    "NBS", "NC", "NCC", "NCD", "NCE", "NCG",
    "NCH", "NCL", "NCT", "NDC", "NDMR", "NDR",
    "NDT", "NE", "NEB", "NEC", "NEEL", "NEFT",
    "NEG", "NEI", "NEST", "NG", "NH", "NHA",
    "NHL", "NMR", "NN", "NNA", "NO", "NOC",
    "NOVA", "NR", "NRC", "NRR", "NS", "NSE",
    "NSI", "NSN", "NSS", "NST", "NTA", "NTPC",
    "NTS", "NTV", "NUE", "NV", "NVA", "NVG",
    "NVX", "NYC", "O", "OA", "OIL", "ONGC",
    "OP", "OR", "ORC", "ORCL", "ORD", "ORF",
    "ORG", "ORS", "ORZ", "OS", "OSA", "OSE",
    "OSG", "OSS", "OST", "OTH", "OTM", "OXY",
    "P1", "P2C", "P2L", "P2O", "PA", "PACC",
    "PADMA", "PAF", "PAL", "PAM", "PAN", "PANA",
    "PANDE", "PARG", "PAREN", "PART", "PASS", "PAT",
    "PB", "PBR", "PC", "PCA", "PCC", "PCG",
    "PCH", "PCL", "PCR", "PCT", "PCU", "PCW",
    "PD", "PDE", "PDG", "PDL", "PDP", "PE",
    "PEARL", "PECT", "PEL", "PEN", "PER",
    "PES", "PET", "PETA", "PETM", "PEX", "PF",
    "PFC", "PFF", "PFG", "PFH", "PFIN", "PFL",
    "PFN", "PFO", "PFS", "PGR", "PGU", "PGUK",
    "PH", "PHA", "PHB", "PIA", "PIF", "PIG",
    "PIL", "PION", "PIP", "PJ", "PIRE", "PJR",
    "PK", "PKA", "PKE", "PKG", "PKH", "PKL",
    "PKN", "Pks", "PKT", "PLC", "PLF", "PLG",
    "PLNG", "PLR", "PLS", "PLT", "PLU", "PLUG",
    "PLUS", "PM", "PMC", "PMI", "PMN", "PMS", "PN",
    "PNB", "PNC", "PNG", "PNH", "PNL", "PNM",
    "PNR", "PNS", "PNU", "PO", "POC", "POKEMON",
    "POLIO", "POR", "PORT", "POS", "POST", "POUL",
    "POW", "POWER", "PP", "PPA", "PPC", "PPG",
    "PPI", "PPM", "PQU", "PR", "PRA", "PRAT",
    "PRD", "PRDA", "PRDO", "PRE", "PRFL", "PRFO",
    "PRG", "PRH", "PRIM", "PRISMA", "PRJ", "PRM",
    "PRP", "PRPT", "PRR", "PRS", "PRST", "PSU",
    "PSX", "PT", "PTA", "PTE", "PTEL", "PTF",
    "PTL", "PTM", "PTN", "PTO", "PU", "PUL",
    "PUN", "PUT", "PV", "PWB", "PY", "PZA",
    "Q", "R1", "R2C", "R2F", "RA", "RAD",
    "RAJ", "RAJA", "RAJB", "RALL", "RAM", "RAMC",
    "RAME", "RAMP", "RAN", "RAND", "RAR", "RAT",
    "RAU", "RBR", "RC", "RCA", "RCB", "RCC",
    "RCE", "RCF", "RCL", "RCM", "RCN", "RCP",
    "RCS", "RCT", "RCUK", "RCW", "RD", "RDB",
    "RDE", "RDM", "RDS", "RDX", "RE", "REC",
    "RED", "REF", "REG", "REI", "RELIANCE", "REL",
    "REM", "REN", "RENT", "REP", "RER", "RET",
    "RFF", "RFL", "RFR", "RH", "RHE", "RHI",
    "RHL", "RHM", "RHR", "RHS", "RHV", "RHY",
    "RIALTO", "RIL", "RINF", "RIP", "RIS", "RIV",
    "RJT", "RK", "RKC", "RKE", "RKH", "RKL",
    "RKM", "RKP", "RKR", "RLF", "RLR", "RLS",
    "RM", "RMC", "RMD", "RMG", "RMK", "RML",
    "RMS", "RMT", "RMZ", "RNA", "RND", "RO",
    "ROCA", "ROCK", "ROCL", "ROF", "ROG", "ROK",
    "ROL", "ROMA", "ROOM", "ROOS", "ROP", "ROR",
    "ROS", "ROT", "ROX", "RT", "RTA", "RTC",
    "RTG", "RTH", "RTL", "RTM", "RTO", "RTR",
    "RTS", "RTT", "RTW", "RUB", "RUC", "RUCH",
    "RUDA", "RUF", "RUI", "RUP", "RUPEE", "RUS",
    "RUT", "RVI", "S1", "S2", "S3", "SA",
    "SAB", "SAC", "SAD", "SAE", "SAF", "SAI",
    "SALASAR", "SAM", "SAMA", "SAME", "SAMP", "SAMT",
    "SAN", "SANDESH", "SANE", "SANM", "SANSERA", "SAP",
    "SAR", "SARA", "SAS", "SASE", "SAT", "SATV",
    "SAV", "SB", "SBC", "SBD", "SBG", "SBH",
    "SBIB", "SBN", "SBP", "SBR", "SBU", "SBUX",
    "SC", "SCA", "SCB", "SCC", "SCD", "SCF",
    "SCH", "SCI", "SCN", "SCO", "SCR", "SCT",
    "SD", "SDA", "SDB", "SDC", "SDG", "SDH",
    "SDL", "SDM", "SDN", "SDO", "SDR", "SDSL",
    "SDX", "SE", "SEA", "SEE", "SEIL", "SEL",
    "SER", "SEW", "SF", "SFA", "SFC", "SFF",
    "SFG", "SFL", "SFM", "SFO", "SFR", "SFW",
    "SG", "SGA", "SGC", "SGD", "SGE", "SGL",
    "SGN", "SGP", "SGR", "SGS", "SH", "SHA",
    "SHAL", "SHB", "SHC", "SHD", "SHG", "SHH",
    "SHI", "SHJ", "SHK", "SHL", "SHM", "SHN",
    "SHO", "SHP", "SHR", "SHT", "SHU", "SHV",
    "SID", "SII", "SIL", "SIM", "SIN", "SIP",
    "SJ", "SK", "SKF", "SKG", "SL", "SLA",
    "SLB", "SLE", "SLG", "SLK", "SLL", "SLM",
    "SLN", "SLNG", "SLO", "SLP", "SLR", "SLS",
    "SLT", "SLV", "SM", "SMA", "SMB", "SMC",
    "SMCL", "SMD", "SME", "SMG", "SMH", "SMIG",
    "SML", "SMM", "SMQ", "SMR", "SMS", "SMT",
    "SN", "SNC", "SNG", "SNL", "SNP", "SNV",
    "SNX", "SO", "SOBHA", "SOC", "SOE", "SOF",
    "SOL", "SOMA", "SOM", "SON", "SOP", "SOS",
    "SOT", "SP", "SPA", "SPB", "SPC", "SPD",
    "SPG", "SPI", "SPK", "SPM", "SPR", "SPS",
    "SR", "SRD", "SRE", "SRF", "SRG", "SRH",
    "SRI", "SRN", "SRP", "SRR", "SRS", "SRT",
    "SRU", "SS", "SSA", "SSB", "SSC", "SSD",
    "SSF", "SSI", "SSL", "SSN", "SSP", "SST",
    "ST", "SZA", "TC", "TCC", "TCE", "TCI",
    "TCN", "TCP", "TCR", "TD", "TDI", "TEA",
    "TED", "TERM", "TES", "TFB", "TFG", "TFP",
    "TFW", "TG", "TGB", "TGD", "TGT", "TH",
    "THB", "THF", "THG", "THM", "THP", "THQ",
    "THR", "THT", "TI", "TIN", "TIP", "TIS",
    "TIT", "TIW", "TJ", "TJA", "TJB", "TJK",
    "TJS", "TK", "TKC", "TKL", "TKO", "TKP",
    "TL", "TLA", "TLC", "TLE", "TLG", "TLH",
    "TLL", "TLM", "TLN", "TLO", "TLP", "TLR",
    "TLS", "TLT", "TM", "TMA", "TMB", "TMC",
    "TME", "TMG", "TML", "TMP", "TMS", "TMV",
    "TN", "TNA", "TNB", "TNC", "TNE", "TNG",
    "TNK", "TNL", "TNP", "TNR", "TNS", "TOC",
    "TOD", "TOI", "TORNADO", "TOT", "TOWER", "TP",
    "TPC", "TPI", "TPL", "TPM", "TPN", "TPR",
    "TRA", "TRB", "TREF", "TRG", "TRI", "TRL",
    "TRM", "TRN", "TRO", "TRP", "TRQ", "TRS",
    "TRT", "TRV", "TS", "TSA", "TSB", "TSL",
    "TSM", "TT", "TU", "TUK", "TUL", "TV",
    "TVS", "TW", "TX", "U1", "U2", "UA",
    "UBE", "UBI", "UBM", "UC", "UCH", "UCL",
    "UD", "UDC", "UDF", "UDI", "UDR", "UE",
    "UEC", "UEM", "UES", "UFA", "UFC", "UFL",
    "UGA", "UGE", "UGRO", "UH", "UK", "UKB",
    "UL", "UN", "UNA", "UNB", "UNI", "UNION",
    "UNIQ", "US", "USF", "USL", "USP", "USS",
    "UT", "UTE", "VI", "VJ", "VOC", "VON",
    "VRL", "VS", "VSE", "VT", "VU", "VX", "W1",
    "WA", "WARD", "WBI", "WC", "WCC", "WCG",
    "WCR", "WD", "WDR", "WE", "WEL", "WEST",
    "WF", "WFB", "WFS", "WGC", "WGH", "WH",
    "WIA", "WII", "WIS", "WIT", "WL", "WLC",
    "WLS", "WLW", "WM", "WMC", "WME", "WMP",
    "WMS", "WNC", "WNS", "WOM", "WOO", "WOP",
    "WOR", "WPC", "WPP", "WPS", "WR", "WS",
    "WSC", "WSI", "WST", "WT", "WTC", "WTI",
    "WTS", "WTT", "WU", "WUC", "WV", "WVM",
    "WW", "WY", "X", "XB", "XC", "XCM", "XCP",
    "XE", "XEC", "XEL", "XEN", "XES", "XI",
    "XIA", "XIN", "XL", "XM", "XMH", "XMP",
    "XMS", "XOR", "XOXO", "XPA", "XPC", "XPL",
    "XPO", "XR", "XSD", "XSN", "XT", "XU", "XX",
    "XY", "Y1", "Y2", "YA", "YAM", "YAT",
    "YCC", "YD", "YDA", "YDC", "YDL", "YDS",
    "YE", "YEA", "YES", "YGS", "YIL", "YIN",
    "YIW", "YLC", "YLL", "YLM", "YLT", "YM",
    "YOC", "YOD", "YOK", "YON", "YP", "YPN",
    "YR", "YS", "YSD", "YSL", "YT", "YTC",
    "YTL", "YTM", "YTV", "YUX", "Z1", "Z2",
    "Z3", "Z5", "Z7", "Z9", "ZA", "ZB",
    "ZD", "ZE", "ZEBRA", "ZEN", "ZENE", "ZERO",
    "ZEUS", "ZG", "ZHC", "ZI", "ZIL", "ZIR",
    "ZM", "ZMD", "ZODIAC", "ZOO", "ZR", "ZRC",
    "ZS", "ZSC", "ZSL", "ZSN", "ZU", "ZUS",
    "ZV", "ZWA", "ZX", "ZZ",
]


def scan_universe_parallel(top_n: int = TOP_N_RESULTS) -> list[dict[str, Any]]:
    """
    Main function: Scan full NSE universe with parallel workers.
    
    Returns top_n stocks ranked by composite score.
    """
    global LAST_SCAN_DIAGNOSTICS
    import logging
    logger = logging.getLogger("universe_scanner")
    
    logger.info("=== Starting Universe Scan (parallel) ===")
    
    # Get full universe
    universe = get_full_universe()
    logger.info(f"Universe size: {len(universe)} stocks")
    
    if not universe:
        logger.warning("Empty universe, using fallback")
        universe = _EXTENDED_UNIVERSE
        logger.info(f"Fallback universe size: {len(universe)} stocks")
    
    # Partition into batches
    batch_size = max(1, len(universe) // WORKER_COUNT)
    batches = [
        universe[i:i+batch_size] 
        for i in range(0, len(universe), batch_size)
    ]
    batches = batches[:WORKER_COUNT]  # Limit to worker count
    
    logger.info(f"Partitioned into {len(batches)} batches")
    
    # Parallel execution
    all_results = []
    scan_stats: dict[str, int] = {
        "symbols": 0,
        "passed": 0,
        "no_nse_symbol": 0,
        "no_data": 0,
        "price_below_filter": 0,
        "volume_below_filter": 0,
        "error": 0,
        "batch_failures": 0,
    }
    start_time = time.time()
    
    with ProcessPoolExecutor(max_workers=WORKER_COUNT) as executor:
        futures = {executor.submit(_batch_analyze, batch): i 
                   for i, batch in enumerate(batches)}
        
        for future in as_completed(futures):
            batch_idx = futures[future]
            try:
                batch_result = future.result(timeout=300)
                results = batch_result.get("results", [])
                for key, value in (batch_result.get("stats", {}) or {}).items():
                    scan_stats[key] = scan_stats.get(key, 0) + int(value or 0)
                all_results.extend(results)
                logger.info(f"Batch {batch_idx+1}/{len(batches)} done: {len(results)} results")
            except Exception as e:
                scan_stats["batch_failures"] += 1
                logger.error(f"Batch {batch_idx} failed: {e}")
    
    elapsed = time.time() - start_time
    logger.info(f"Scanned {len(all_results)} candidates in {elapsed/60:.1f} min")
    LAST_SCAN_DIAGNOSTICS = {
        **scan_stats,
        "universe_size": len(universe),
        "batches": len(batches),
        "candidates_found": len(all_results),
        "elapsed_seconds": round(elapsed, 2),
    }
    logger.info("Universe scan diagnostics: %s", LAST_SCAN_DIAGNOSTICS)
    
    if not all_results:
        logger.warning("No results from universe scan")
        return []
    
    # Rank by score
    ranked = sorted(all_results, key=lambda x: x.get("score", 0), reverse=True)
    top_stocks = ranked[:top_n]
    
    logger.info(f"Top {top_n} by score: {[s['symbol'] for s in top_stocks]}")
    
    return top_stocks


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    results = scan_universe_parallel(20)
    for r in results:
        print(f"{r['symbol']}: score={r['score']:.1f} price={r['price']:.2f} rsi={r['rsi']:.1f}")
