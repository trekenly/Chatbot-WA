"""
Intent + JSON Schema validation endpoints.

These endpoints sit between an LLM (which outputs normalized intent JSON)
and the deterministic ticketing orchestrator.

Step 1: /validate  (schema gate)
Step 2: /parse     (draft intent from unstructured text; may be incomplete)
"""

from __future__ import annotations

import re
import difflib
from datetime import date, timedelta
from typing import Any, Dict, List, Optional, Tuple
from pathlib import Path
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.busx.schema.schema_validate import validate_normalized_intent
from app.utils.dates import local_today_date
from app.utils.stop_aliases import ALIASES

# -----------------------------
# Thailand city/province catalog (auto)
#
# We load canonical keyword_name values from from_keywords.json shipped with the repo.
# This lets NLP resolve *any* Thai city/province even if it's not explicitly in ALIASES.
# -----------------------------

_CITY_CHOICES: List[str] = []


def _load_city_choices() -> List[str]:
    try:
        # This file lives at ChatBot_V11/from_keywords.json in the project.
        here = Path(__file__).resolve()
        root = here.parents[3]  # .../ChatBot_V11
        fp = root / "from_keywords.json"
        if not fp.exists():
            return []
        data = json.loads(fp.read_text(encoding="utf-8"))
        items = data.get("data") or []
        out: List[str] = []
        seen = set()
        for it in items:
            name = (it or {}).get("keyword_name") or (it or {}).get("state_province_name")
            name = (name or "").strip()
            if not name:
                continue
            k = _norm_text(name)
            if k and k not in seen:
                seen.add(k)
                out.append(name)
        return out
    except Exception:
        return []


_CITY_CHOICES = _load_city_choices()

# -----------------------------
# NLP normalization helpers
# -----------------------------
_REPEAT_RE = re.compile(r"(.)\1{2,}")          # collapse 3+ repeats
_PUNCT_RE  = re.compile(r"[^a-z0-9ก-๙\s]")

_TOMORROW_SLOPPY_RE = re.compile(
    r"\bto(?:m+)(?:o+)?r{1,2}ow\b|\btorr?ow\b|\btom?or?ow\b",
    re.IGNORECASE,
)
_TODAY_SLOPPY_RE = re.compile(r"\btod+a+y\b", re.IGNORECASE)

_PAX_RE = re.compile(r"\b(\d{1,2})\s*(ppl|people|pax|tickets?)\b", re.IGNORECASE)

def _norm_text(s: str) -> str:
    s = (s or "").strip().lower()
    s = _PUNCT_RE.sub(" ", s)
    s = _REPEAT_RE.sub(r"\1\1", s)   # tomooorow -> tomorow
    s = re.sub(r"\s+", " ", s).strip()
    return s

def _contains_today(t: str) -> bool:
    return bool(_TODAY_SLOPPY_RE.search(t or ""))

def _contains_tomorrow(t: str) -> bool:
    return bool(_TOMORROW_SLOPPY_RE.search(t or ""))

def _extract_pax(t: str):
    m = _PAX_RE.search(t or "")
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None

def _clean_place_phrase(s: str) -> str:
    """Remove leading glue words like 'from' and trim extra filler."""
    if not s:
        return ""
    t = _norm_text(s)
    # remove leading 'from' / 'depart' / 'departure'
    t = re.sub(r"^(from|frm|depart|departure)\s+", "", t, flags=re.IGNORECASE)
    # remove trailing glue
    t = re.sub(r"\s+(to|towards)$", "", t, flags=re.IGNORECASE)
    return t.strip()

def _resolve_alias(token: str):
    if not token:
        return None
    raw = token.strip()
    k = _norm_text(raw)

    def _pick(v):
        # ALIASES values may be list[str] or str (EXTRA_ALIASES injects strings)
        if v is None:
            return None
        if isinstance(v, list):
            return v[0] if v else None
        if isinstance(v, str):
            return v
        return str(v)

    if k in ALIASES:
        return _pick(ALIASES[k])
    k2 = k.replace(" ", "")
    if k2 in ALIASES:
        return _pick(ALIASES[k2])

    up = raw.upper()
    if up in ALIASES:
        return _pick(ALIASES[up])

    return None

def _fuzzy_best(token: str, choices):
    tn = _norm_text(token)
    best = None
    best_s = 0.0
    for c in choices:
        s = difflib.SequenceMatcher(None, tn, _norm_text(c)).ratio() * 100.0
        if s > best_s:
            best = c
            best_s = s
    return best, best_s

def _resolve_place(token: str, min_score: float = 82.0):
    a = _resolve_alias(token)
    if a:
        return a
    # 1) fuzzy over alias keys (terminals, abbreviations, etc.)
    keys = list(ALIASES.keys())
    best_key, score = _fuzzy_best(token, keys)
    if best_key and score >= min_score:
        v = ALIASES.get(best_key)
        if isinstance(v, list):
            return v[0] if v else None
        if isinstance(v, str):
            return v
        return str(v) if v is not None else None

    # 2) fuzzy over Thailand city/province catalog (from_keywords.json)
    if _CITY_CHOICES:
        best_city, score2 = _fuzzy_best(token, _CITY_CHOICES)
        if best_city and score2 >= max(min_score, 86.0):
            return best_city
    return None

def _extract_places_anywhere(raw: str):
    t = _norm_text(raw)
    toks = [x for x in t.split() if x and x not in {'from','to','frm','depart','departure'}]
    found = []
    for w in (3, 2, 1):
        for i in range(0, max(0, len(toks) - w + 1)):
            chunk = " ".join(toks[i:i+w])
            canon = _resolve_place(chunk)
            if canon and canon not in found:
                found.append(canon)
                if len(found) >= 2:
                    return found
    return found


router = APIRouter(prefix="/busx/intent", tags=["intent"])


# -----------------------------
# Models
# -----------------------------

class ValidateResponse(BaseModel):
    ok: bool = True
    errors: List[str] = Field(default_factory=list)


class ParseRequest(BaseModel):
    text: str
    locale: Optional[str] = "en_US"
    time_zone: Optional[str] = "Asia/Bangkok"
    currency: Optional[str] = "THB"


class ParseResponse(BaseModel):
    ok: bool = True
    intent_envelope: Dict[str, Any] = Field(default_factory=dict)
    missing_fields: List[str] = Field(default_factory=list)
    notes: List[str] = Field(default_factory=list)


# -----------------------------
# Existing: validate
# -----------------------------

@router.post("/validate", response_model=ValidateResponse)
async def validate_intent(payload: Dict[str, Any]) -> ValidateResponse:
    """Validate an LLM-produced intent envelope against JSON Schemas."""
    errors = validate_normalized_intent(payload)
    if errors:
        raise HTTPException(status_code=422, detail={"ok": False, "errors": errors})
    return ValidateResponse(ok=True, errors=[])


# -----------------------------
# Step 2: parse (draft)
# -----------------------------

_DATE_RE = re.compile(r"\b(20\d{2})-(\d{2})-(\d{2})\b")
_INT_RE = re.compile(r"\b(\d{1,2})\b")

# quick multilingual keyword map for today/tomorrow (very small on purpose)
_TODAY_WORDS = {"today", "tod", "วันนี้", "今日", "hoy", "aujourd'hui", "heute", "oggi"}
_TOMORROW_WORDS = {"tomorrow", "tmr", "พรุ่งนี้", "明日", "mañana", "demain", "morgen", "domani"}

# some pax markers across languages
_PAX_MARKERS = {
    "ticket", "tickets", "pax", "people", "person", "persons",
    "adult", "adults",
    "คน", "ที่นั่ง", "ใบ",
}

# from/to patterns (keep simple)
_FROM_TO_PATTERNS: List[Tuple[re.Pattern, Tuple[int, int]]] = [
    # English: "Bangkok to Phuket"
    (re.compile(r"^\s*(.+?)\s+to\s+(.+?)\s*$", re.I), (1, 2)),
    # Arrow: "Bangkok -> Phuket" or "Bangkok - Phuket"
    (re.compile(r"^\s*(.+?)\s*(->|→|-)\s*(.+?)\s*$", re.I), (1, 3)),
    # Thai: "จาก X ไป Y"
    (re.compile(r"^\s*จาก\s+(.+?)\s+ไป\s+(.+?)\s*$", re.I), (1, 2)),
    # Spanish: "de X a Y"
    (re.compile(r"^\s*de\s+(.+?)\s+a\s+(.+?)\s*$", re.I), (1, 2)),
]


def _detect_language_heuristic(text: str) -> str:
    t = text or ""
    # Thai block
    if re.search(r"[\u0E00-\u0E7F]", t):
        return "th"
    # CJK
    if re.search(r"[\u4E00-\u9FFF]", t):
        return "zh"
    # Spanish-ish
    if "mañana" in t.lower():
        return "es"
    # default
    return "en"


def _parse_date(text: str) -> Optional[str]:
    t = _norm_text(text)
    if not t:
        return None

    # sloppy today/tomorrow
    if _contains_today(t):
        return local_today_date().isoformat()
    if _contains_tomorrow(t):
        return (local_today_date() + timedelta(days=1)).isoformat()
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

    # word-based today/tomorrow
    for w in _TOMORROW_WORDS:
        if w in t:
            return (today + timedelta(days=1)).isoformat()
    for w in _TODAY_WORDS:
        if w in t:
            return today.isoformat()

    return None


def _parse_pax(text: str) -> Optional[int]:
    t = (text or "").strip().lower()
    if not t:
        return None

    # prefer "N ticket(s)/pax/คน/ใบ" forms
    for m in re.finditer(r"\b(\d{1,2})\b", t):
        n = int(m.group(1))
        if not (1 <= n <= 20):
            continue

        # look rightward for marker
        tail = t[m.end(): m.end() + 20]
        if any(k in tail for k in _PAX_MARKERS):
            return n

    # fallback: if exactly one small number exists, treat it as pax
    nums = _INT_RE.findall(t)
    if len(nums) == 1:
        n = int(nums[0])
        return n if 1 <= n <= 20 else None

    return None


def _strip_known_noise(text: str) -> str:
    # remove date and pax-ish fragments to make from/to parsing easier
    t = text

    t = _DATE_RE.sub(" ", t)
    # remove obvious pax chunks like "1 ticket", "2 pax", "3 คน"
    t = re.sub(r"\b\d{1,2}\b\s*(tickets?|pax|ppl|people|persons?|adult|adults)\b", " ", t, flags=re.I)
    t = re.sub(r"\b\d{1,2}\b\s*(คน|ที่นั่ง|ใบ)\b", " ", t, flags=re.I)

    # remove today/tomorrow words
    for w in sorted(_TODAY_WORDS | _TOMORROW_WORDS, key=len, reverse=True):
        t = re.sub(re.escape(w), " ", t, flags=re.I)

    # remove sloppy variants like tomooorow
    t = _TOMORROW_SLOPPY_RE.sub(' ', t)
    t = _TODAY_SLOPPY_RE.sub(' ', t)

    # normalize whitespace
    t = re.sub(r"\s+", " ", t).strip()
    return t


def _parse_from_to(text: str) -> Tuple[Optional[str], Optional[str]]:
    t0 = _strip_known_noise(text)
    if not t0:
        return None, None

    # Try patterns against the full remaining string
    for pat, (gi, gj) in _FROM_TO_PATTERNS:
        m = pat.search(t0)
        if m:
            a = (m.group(gi) or "").strip()
            b = (m.group(gj) or "").strip()
            if a and b:
                a2=_clean_place_phrase(a)
                b2=_clean_place_phrase(b)
                return _resolve_place(a2) or a2 or a, _resolve_place(b2) or b2 or b

    # Fallback: detect up to 2 places anywhere in the text (supports non-native spelling & missing 'to')
    places = _extract_places_anywhere(t0 or text)
    if len(places) >= 2:
        return places[0], places[1]
    return None, None


@router.post("/parse", response_model=ParseResponse)
async def parse_intent(req: ParseRequest) -> ParseResponse:
    """
    Draft intent parsing from unstructured text.

    IMPORTANT:
    - This output is allowed to be incomplete.
    - Use missing_fields to drive follow-up questions.
    - When complete, you can call /validate (or validate internally).
    """
    raw = (req.text or "").strip()
    if not raw:
        raise HTTPException(status_code=422, detail={"ok": False, "errors": ["text is required"]})

    detected_lang = _detect_language_heuristic(raw)
    dep_date = _parse_date(raw)
    pax = _parse_pax(raw)
    from_name, to_name = _parse_from_to(raw)

    missing: List[str] = []
    if not from_name:
        missing.append("from.name")
    if not to_name:
        missing.append("to.name")
    if not dep_date:
        missing.append("departure_date")
    if not pax:
        missing.append("passengers.adult_count")

    # Draft normalized envelope (LLM can do better later; this is deterministic baseline)
    envelope: Dict[str, Any] = {
        "intent": "TripSearch",
        "confidence": 0.55,  # heuristic baseline
        "original_text": raw,
        "detected_language": detected_lang,
        "locale": req.locale or "en_US",
        "time_zone": req.time_zone or "Asia/Bangkok",
        "currency": (req.currency or "THB").upper(),
        "payload": {
            "trip_search": {
                "journey_type": "OW",
                "departure_date": dep_date,
                "from": {"name": from_name} if from_name else {},
                "to": {"name": to_name} if to_name else {},
                "passengers": {"adult_count": pax} if pax else {},
            }
        },
    }

    notes: List[str] = []
    notes.append(f"parsed_date={dep_date or ''}".strip())
    notes.append(f"parsed_pax={pax or ''}".strip())
    notes.append(f"parsed_from={from_name or ''}".strip())
    notes.append(f"parsed_to={to_name or ''}".strip())

    return ParseResponse(ok=True, intent_envelope=envelope, missing_fields=missing, notes=notes)