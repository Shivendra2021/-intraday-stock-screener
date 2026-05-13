from __future__ import annotations

import datetime as dt

IST = dt.timezone(dt.timedelta(hours=5, minutes=30), name="IST")


def now_ist() -> dt.datetime:
    return dt.datetime.now(IST).replace(tzinfo=None)


def today_ist() -> dt.date:
    return now_ist().date()


def today_ist_str() -> str:
    return today_ist().isoformat()
