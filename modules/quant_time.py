"""Timezone-aware clock for portable quant timestamps (including cloud UTC hosts)."""
import datetime as dt

IST = dt.timezone(dt.timedelta(hours=5, minutes=30))


def now_ist():
    return dt.datetime.now(IST)


def today_ist_str():
    return now_ist().strftime("%Y-%m-%d")
