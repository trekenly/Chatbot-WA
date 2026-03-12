from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Dict, Optional

from app.utils.dates import local_today_date


def _guess_date(text: str) -> Optional[str]:
    t = (text or "").lower()
    today = local_today_date()
    if "tomorrow" in t:
        return (today + timedelta(days=1)).isoformat()
    if "today" in t:
        return today.isoformat()
    return None


def normalize_intent_stub(
    text: str,
    *,
    locale: str = "en_US",
    time_zone: str = "Asia/Bangkok",
    currency: str = "THB",
) -> Dict[str, Any]:
    """
    Step-2 stub: returns a deterministic NormalizedIntent-like object.
    This is NOT an LLM yet — it's a placeholder so the endpoint + wiring are correct.
    """

    dep = _guess_date(text) or date.today().isoformat()

    # very naive from/to extraction (placeholder)
    # "Bangkok to Phuket ..." => from=Bangkok, to=Phuket
    from_name = None
    to_name = None
    lower = (text or "").strip()
    if " to " in lower.lower():
        parts = lower.split(" to ", 1)
        from_name = parts[0].strip().title() or None
        tail = parts[1].strip()
        to_name = tail.split()[0].strip().title() if tail else None

    return {
        "intent": "TripSearch",
        "confidence": 0.50,
        "original_text": text,
        "detected_language": None,
        "locale": locale,
        "time_zone": time_zone,
        "currency": currency,
        "payload": {
            "trip_search": {
                "journey_type": "OW",
                "departure_date": dep,
                "from": {"name": from_name or ""},
                "to": {"name": to_name or ""},
                "passengers": {"adult_count": 1},
            }
        },
    }
