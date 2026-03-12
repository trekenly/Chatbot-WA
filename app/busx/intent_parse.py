# app/busx/intent_parse.py
from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Dict, Optional, Tuple

from pydantic import BaseModel, Field

from app.utils.dates import local_today_date


class ParseRequest(BaseModel):
    text: str = Field(..., min_length=1)
    locale: str = Field(default="en_US")
    time_zone: str = Field(default="Asia/Bangkok")
    currency: str = Field(default="THB")


_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_PAX_LABELED_RE = re.compile(r"\b(\d{1,2})\s*(tickets?|pax|people|persons?)\b", re.I)
_PAX_PLAIN_RE = re.compile(r"^\d{1,2}$")


def _detect_language(text: str) -> str:
    # lightweight heuristic; you’ll replace/augment later with LLM detection
    for ch in text:
        code = ord(ch)
        if 0x0E00 <= code <= 0x0E7F:
            return "th"
        if 0x4E00 <= code <= 0x9FFF:
            return "zh"
        if 0x3040 <= code <= 0x30FF:
            return "ja"
        if 0xAC00 <= code <= 0xD7AF:
            return "ko"
    return "en"


def _parse_date(text: str) -> Optional[str]:
    t = (text or "").strip().lower()
    if not t:
        return None

    m = _DATE_RE.search(t)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d.isoformat()
        except Exception:
            return None

    today = local_today_date()
    if "tomorrow" in t:
        return (today + timedelta(days=1)).isoformat()
    if "today" in t:
        return today.isoformat()
    return None


def _parse_pax(text: str) -> Optional[int]:
    t = (text or "").strip()
    if not t:
        return None

    tl = t.lower()

    # "2 pax"
    m = _PAX_LABELED_RE.search(tl)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 20 else None

    # plain "2"
    if _PAX_PLAIN_RE.fullmatch(tl):
        n = int(tl)
        return n if 1 <= n <= 20 else None

    return None


def _parse_route_names(text: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Very small heuristic:
      - English: "A to B"
      - Thai: "จาก A ไป B"
    """
    t = (text or "").strip()

    # Thai "จาก X ไป Y"
    m = re.search(r"จาก\s+(.+?)\s+ไป\s+(.+)", t)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    # English "A to B"
    m = re.search(r"(.+?)\s+to\s+(.+)", t, flags=re.I)
    if m:
        return m.group(1).strip(), m.group(2).strip()

    return None, None


def parse_normalized_intent(req: ParseRequest) -> Dict[str, Any]:
    text = (req.text or "").strip()

    detected_language = _detect_language(text)
    departure_date = _parse_date(text)
    pax = _parse_pax(text) or 1
    frm, to = _parse_route_names(text)

    missing = []
    if not departure_date:
        missing.append("payload.trip_search.departure_date")
    if not frm:
        missing.append("payload.trip_search.from.name")
    if not to:
        missing.append("payload.trip_search.to.name")

    # Option A: Only emit TripSearch if it is schema-valid (all required fields present)
    if missing:
        return {
            "intent": "Unknown",
            "confidence": 0.0,
            "original_text": text,
            "detected_language": detected_language,
            "locale": req.locale,
            "time_zone": req.time_zone,
            "currency": req.currency,
            "payload": {},
            "missing_fields": missing,
        }

    return {
        "intent": "TripSearch",
        "confidence": 0.8,
        "original_text": text,
        "detected_language": detected_language,
        "locale": req.locale,
        "time_zone": req.time_zone,
        "currency": req.currency,
        "payload": {
            "trip_search": {
                "journey_type": "OW",
                "departure_date": departure_date,
                "from": {"name": frm},
                "to": {"name": to},
                "passengers": {"adult_count": pax},
            }
        },
        "missing_fields": [],
    }
