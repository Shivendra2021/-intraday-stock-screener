"""Analyze historical top movers and store reusable Monday learning patterns."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import sqlite3
import sys
from collections import Counter
from statistics import mean, median
from typing import Any

import pandas as pd

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from tools.send_friday_top_movers import scan_top_movers


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        val = float(value)
        if math.isnan(val) or math.isinf(val):
            return default
        return val
    except Exception:
        return default


def _ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False, min_periods=span).mean()


def _rsi(close: pd.Series, length: int = 14) -> float:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / length, min_periods=length, adjust=False).mean()
    rs = gain / loss.replace(0, pd.NA)
    return _to_float((100 - 100 / (1 + rs)).fillna(50).iloc[-1], 50.0)


def _atr_pct(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> float:
    prev_close = close.shift(1)
    true_range = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr = _to_float(true_range.ewm(alpha=1 / length, min_periods=length, adjust=False).mean().iloc[-1])
    price = _to_float(close.iloc[-1])
    return atr / price * 100 if price > 0 else 0.0


def _adx(high: pd.Series, low: pd.Series, close: pd.Series, length: int = 14) -> float:
    up = high.diff()
    down = -low.diff()
    plus_dm = pd.Series(((up > down) & (up > 0)) * up, index=high.index).fillna(0.0)
    minus_dm = pd.Series(((down > up) & (down > 0)) * down, index=low.index).fillna(0.0)
    prev_close = close.shift(1)
    tr = pd.concat([high - low, (high - prev_close).abs(), (low - prev_close).abs()], axis=1).max(axis=1)
    atr = tr.ewm(alpha=1 / length, min_periods=length, adjust=False).mean().replace(0, pd.NA)
    plus_di = 100 * plus_dm.ewm(alpha=1 / length, min_periods=length, adjust=False).mean() / atr
    minus_di = 100 * minus_dm.ewm(alpha=1 / length, min_periods=length, adjust=False).mean() / atr
    dx = (plus_di - minus_di).abs() / (plus_di + minus_di).replace(0, pd.NA) * 100
    return _to_float(dx.ewm(alpha=1 / length, min_periods=length, adjust=False).mean().fillna(20).iloc[-1], 20.0)


def _normalize_download(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [str(c[0]).lower() for c in df.columns]
    else:
        df.columns = [str(c).lower() for c in df.columns]
    return df.dropna(subset=["close"]) if "close" in df.columns else pd.DataFrame()


def _history(symbol: str, target: dt.date) -> pd.DataFrame:
    import yfinance as yf
    from modules.fetch import SYMBOL_ALIASES

    alias = SYMBOL_ALIASES.get(symbol, symbol)
    start = (target - dt.timedelta(days=140)).isoformat()
    end = (target + dt.timedelta(days=1)).isoformat()
    for ticker in (f"{alias}.NS", f"{alias}.BO"):
        try:
            df = yf.download(ticker, start=start, end=end, interval="1d", auto_adjust=True, progress=False)
            df = _normalize_download(df)
            if not df.empty and len(df) >= 35:
                return df
        except Exception:
            continue
    return pd.DataFrame()


def _feature_for(symbol: str, target: dt.date, mover: dict[str, Any]) -> dict[str, Any] | None:
    df = _history(symbol, target)
    if df.empty:
        return None

    dates = pd.to_datetime(df.index).date
    event_rows = df[dates == target]
    pre = df[dates < target]
    if event_rows.empty or len(pre) < 30:
        return None

    event = event_rows.iloc[0]
    close = pre["close"].astype(float)
    high = pre["high"].astype(float)
    low = pre["low"].astype(float)
    open_s = pre["open"].astype(float)
    volume = pre["volume"].astype(float)

    prev_close = _to_float(close.iloc[-1])
    prev_high_20 = _to_float(high.tail(20).max())
    prev_high_60 = _to_float(high.tail(60).max())
    event_open = _to_float(event["open"])
    event_high = _to_float(event["high"])
    event_close = _to_float(event["close"])
    event_volume = _to_float(event.get("volume", 0))
    avg_vol_20 = _to_float(volume.tail(20).mean())

    ema9 = _to_float(_ema(close, 9).iloc[-1], prev_close)
    ema21 = _to_float(_ema(close, 21).iloc[-1], prev_close)
    ema50 = _to_float(_ema(close, 50).iloc[-1], prev_close)
    if prev_close > ema9 > ema21 > ema50:
        ema_alignment = "EMA_full_bull"
    elif prev_close > ema21:
        ema_alignment = "EMA_partial_bull"
    else:
        ema_alignment = "EMA_bear"

    macd = _ema(close, 12) - _ema(close, 26)
    macd_signal = _ema(macd, 9)
    bb_mid = close.rolling(20).mean()
    bb_std = close.rolling(20).std()
    bb_upper = _to_float((bb_mid + 2 * bb_std).iloc[-1])
    bb_lower = _to_float((bb_mid - 2 * bb_std).iloc[-1])
    bb_range = bb_upper - bb_lower
    bb_position = (prev_close - bb_lower) / bb_range if bb_range > 0 else 0.5

    prior_1d = (prev_close - _to_float(close.iloc[-2])) / _to_float(close.iloc[-2]) * 100 if len(close) >= 2 and _to_float(close.iloc[-2]) > 0 else 0
    prior_3d = (prev_close - _to_float(close.iloc[-4])) / _to_float(close.iloc[-4]) * 100 if len(close) >= 4 and _to_float(close.iloc[-4]) > 0 else 0
    prior_5d = (prev_close - _to_float(close.iloc[-6])) / _to_float(close.iloc[-6]) * 100 if len(close) >= 6 and _to_float(close.iloc[-6]) > 0 else 0

    open_to_high = (event_high - event_open) / event_open * 100 if event_open > 0 else 0
    open_to_close = (event_close - event_open) / event_open * 100 if event_open > 0 else 0
    gap_pct = (event_open - prev_close) / prev_close * 100 if prev_close > 0 else 0
    event_vol_ratio = event_volume / avg_vol_20 if avg_vol_20 > 0 else 0
    pre_vol_ratio = _to_float(volume.iloc[-1]) / avg_vol_20 if avg_vol_20 > 0 else 0
    close_location = (event_close - event_open) / (event_high - event_open) if event_high > event_open else 0

    rsi = _rsi(close)
    adx = _adx(high, low, close)
    atr_pct = _atr_pct(high, low, close)
    dist_20_high = (prev_high_20 - prev_close) / prev_high_20 * 100 if prev_high_20 > 0 else 999
    dist_60_high = (prev_high_60 - prev_close) / prev_high_60 * 100 if prev_high_60 > 0 else 999

    tags = []
    if 45 <= rsi <= 65:
        tags.append("rsi_base_45_65")
    if ema_alignment != "EMA_bear":
        tags.append("above_key_ema")
    if pre_vol_ratio >= 1.2:
        tags.append("pre_volume_build")
    if event_vol_ratio >= 2.0:
        tags.append("event_volume_expansion")
    if gap_pct >= 1.0:
        tags.append("gap_up")
    if event_open >= prev_high_20:
        tags.append("open_breakout_20d")
    elif event_high >= prev_high_20:
        tags.append("intraday_breakout_20d")
    if dist_20_high <= 5:
        tags.append("near_20d_high")
    if prior_5d >= 3:
        tags.append("prior_week_momentum")
    if close_location >= 0.6:
        tags.append("strong_close_location")

    return {
        "symbol": symbol,
        "date": target.isoformat(),
        "open_to_high_pct": round(open_to_high, 4),
        "open_to_close_pct": round(open_to_close, 4),
        "open_price": round(event_open, 4),
        "high_price": round(event_high, 4),
        "close_price": round(event_close, 4),
        "prev_close": round(prev_close, 4),
        "gap_pct": round(gap_pct, 4),
        "event_volume_ratio": round(event_vol_ratio, 4),
        "volume_ratio": round(event_vol_ratio, 4),
        "pre_volume_ratio": round(pre_vol_ratio, 4),
        "rsi": round(rsi, 4),
        "adx": round(adx, 4),
        "atr_pct": round(atr_pct, 4),
        "ema_alignment": ema_alignment,
        "macd_positive": _to_float(macd.iloc[-1]) > _to_float(macd_signal.iloc[-1]),
        "bb_position": round(bb_position, 4),
        "prior_1d_pct": round(prior_1d, 4),
        "prior_3d_pct": round(prior_3d, 4),
        "prior_5d_pct": round(prior_5d, 4),
        "dist_20d_high_pct": round(dist_20_high, 4),
        "dist_60d_high_pct": round(dist_60_high, 4),
        "breakout_20d_open": event_open >= prev_high_20,
        "breakout_20d_high": event_high >= prev_high_20,
        "close_location": round(close_location, 4),
        "tags": tags,
        "pattern_key": _pattern_key(rsi, event_vol_ratio, gap_pct, adx, ema_alignment),
        "source_rank_ohlc": mover,
    }


def _pattern_key(rsi: float, vol_ratio: float, gap_pct: float, adx: float, ema_alignment: str) -> str:
    rsi_bucket = "RSI_45_55" if 45 <= rsi < 55 else ("RSI_55_65" if 55 <= rsi <= 65 else ("RSI_65_75" if 65 < rsi <= 75 else "RSI_other"))
    vol_bucket = "VOL_5x" if vol_ratio >= 5 else ("VOL_3x" if vol_ratio >= 3 else ("VOL_2x" if vol_ratio >= 2 else "VOL_lt2x"))
    gap_bucket = "GAP_2pct" if gap_pct >= 2 else ("GAP_0_2pct" if gap_pct > 0 else "GAP_flat")
    adx_bucket = "ADX_25plus" if adx >= 25 else "ADX_lt25"
    return f"{rsi_bucket}__{vol_bucket}__{gap_bucket}__{adx_bucket}__{ema_alignment}"


def _numeric_summary(features: list[dict[str, Any]], key: str) -> dict[str, float]:
    values = sorted(_to_float(f.get(key)) for f in features)
    if not values:
        return {}
    return {
        "min": round(values[0], 3),
        "median": round(median(values), 3),
        "avg": round(mean(values), 3),
        "max": round(values[-1], 3),
    }


def _learn_rules(features: list[dict[str, Any]], min_support: int = 3) -> list[dict[str, Any]]:
    if not features:
        return []
    total = len(features)
    rules: list[dict[str, Any]] = []

    def add(name: str, matched: list[dict[str, Any]], rule: dict[str, Any]) -> None:
        if len(matched) < min_support:
            return
        rules.append(
            {
                "pattern_key": name,
                "confidence": round(len(matched) / total, 4),
                "support_count": len(matched),
                "avg_return_pct": round(mean(_to_float(x["open_to_high_pct"]) for x in matched), 4),
                "rules": rule,
                "symbols": [x["symbol"] for x in matched],
            }
        )

    for tag, count in Counter(tag for f in features for tag in f.get("tags", [])).most_common():
        add(f"tag:{tag}", [f for f in features if tag in f.get("tags", [])], {"tag": tag})

    for key in ["pattern_key", "ema_alignment"]:
        for value, _ in Counter(f.get(key) for f in features if f.get(key)).most_common():
            add(f"{key}:{value}", [f for f in features if f.get(key) == value], {key: value})

    numeric_rules = [
        ("event_volume_ratio", ">=", 2.0),
        ("event_volume_ratio", ">=", 3.0),
        ("pre_volume_ratio", ">=", 1.2),
        ("gap_pct", ">=", 1.0),
        ("prior_5d_pct", ">=", 3.0),
        ("dist_20d_high_pct", "<=", 5.0),
        ("rsi", "between", (45, 65)),
        ("rsi", "between", (55, 75)),
        ("adx", ">=", 25.0),
        ("close_location", ">=", 0.6),
    ]
    for key, op, threshold in numeric_rules:
        if op == ">=":
            matched = [f for f in features if _to_float(f.get(key)) >= float(threshold)]
            value = f">={threshold}"
        elif op == "<=":
            matched = [f for f in features if _to_float(f.get(key), 999) <= float(threshold)]
            value = f"<={threshold}"
        else:
            lo, hi = threshold
            matched = [f for f in features if lo <= _to_float(f.get(key)) <= hi]
            value = f"{lo}-{hi}"
        add(f"{key}:{value}", matched, {key: value})

    rules.sort(key=lambda r: (r["confidence"], r["avg_return_pct"], r["support_count"]), reverse=True)
    return rules[:30]


def _store(target: dt.date, features: list[dict[str, Any]], rules: list[dict[str, Any]]) -> None:
    from config import DB_PATH
    from modules.db_migrations import ensure_research_tables

    ensure_research_tables()
    os.makedirs("data", exist_ok=True)
    with sqlite3.connect(DB_PATH) as conn:
        for f in features:
            conn.execute(
                """INSERT OR REPLACE INTO after_market_winner_features
                   (date, symbol, return_pct, open_to_high_pct, open_to_close_pct,
                    volume_ratio, gap_pct, rsi, adx, ema_alignment, sector, pattern_key, features_json)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    target.isoformat(),
                    f["symbol"],
                    f["open_to_high_pct"],
                    f["open_to_high_pct"],
                    f["open_to_close_pct"],
                    f["event_volume_ratio"],
                    f["gap_pct"],
                    f["rsi"],
                    f["adx"],
                    f["ema_alignment"],
                    "Unknown",
                    f["pattern_key"],
                    json.dumps(f, ensure_ascii=False),
                ),
            )
        for r in rules:
            conn.execute(
                """INSERT OR REPLACE INTO after_market_learned_patterns
                   (date, pattern_key, confidence, support_count, avg_return_pct, rules_json)
                   VALUES (?, ?, ?, ?, ?, ?)""",
                (
                    target.isoformat(),
                    r["pattern_key"],
                    r["confidence"],
                    r["support_count"],
                    r["avg_return_pct"],
                    json.dumps(r, ensure_ascii=False),
                ),
            )
        conn.commit()

    payload = {
        "date": target.isoformat(),
        "features": features,
        "patterns": rules,
        "summary": build_summary(features, rules),
        "updated_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    out_path = os.path.join("data", f"friday_mover_pattern_analysis_{target.isoformat()}.json")
    with open(out_path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=False)
    with open(os.path.join("data", "after_market_patterns.json"), "w", encoding="utf-8") as fp:
        json.dump(payload, fp, indent=2, ensure_ascii=False)


def build_summary(features: list[dict[str, Any]], rules: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "count": len(features),
        "median_open_to_high_pct": _numeric_summary(features, "open_to_high_pct").get("median", 0),
        "numeric": {
            key: _numeric_summary(features, key)
            for key in [
                "open_to_high_pct",
                "open_to_close_pct",
                "gap_pct",
                "event_volume_ratio",
                "pre_volume_ratio",
                "rsi",
                "adx",
                "prior_5d_pct",
                "dist_20d_high_pct",
                "close_location",
            ]
        },
        "tag_counts": Counter(tag for f in features for tag in f.get("tags", [])).most_common(),
        "ema_counts": Counter(f.get("ema_alignment") for f in features).most_common(),
        "top_rules": rules[:12],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default="2026-05-08")
    parser.add_argument("--top", type=int, default=25)
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--no-store", action="store_true")
    args = parser.parse_args()

    target = dt.date.fromisoformat(args.date)
    movers = scan_top_movers(target, limit=args.limit or None)
    top_movers = movers[: args.top]
    features = []
    for idx, mover in enumerate(top_movers, start=1):
        symbol = mover["symbol"]
        print(f"Analyzing {idx}/{len(top_movers)} {symbol}...", flush=True)
        feature = _feature_for(symbol, target, mover)
        if feature:
            features.append(feature)

    features.sort(key=lambda f: f["open_to_high_pct"], reverse=True)
    rules = _learn_rules(features)
    summary = build_summary(features, rules)

    if not args.no_store:
        _store(target, features, rules)

    print(json.dumps({"summary": summary, "features": features[: args.top], "patterns": rules}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
