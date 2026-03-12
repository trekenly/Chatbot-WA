# app/utils/dates.py
from __future__ import annotations

from datetime import datetime, timedelta, timezone, date
import os

def local_today_date() -> date:
    """
    No tzdata required.
    Uses TIME_ZONE_OFFSET_MINUTES if set (e.g. Thailand = 420).
    Falls back to system local time if not set.
    """
    offset_min = os.getenv("TIME_ZONE_OFFSET_MINUTES", "").strip()
    if offset_min:
        try:
            tz = timezone(timedelta(minutes=int(offset_min)))
            return datetime.now(tz).date()
        except Exception:
            pass
    return datetime.now().date()
