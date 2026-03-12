"""Text parsing utilities.

Keep parsing *separate* from orchestration so it's easier to reason about
what user text can influence.

Key invariants:
1) Date-only input must never be interpreted as a route.
2) Hyphen route delimiter is allowed only when it has spaces: "A - B".
"""

from __future__ import annotations

import re
import unicodedata
from datetime import date, timedelta
from typing import List, Optional, Tuple

from app.utils.dates import local_today_date


_DAY_WORDS = {
    "today": "today",
    "tod": "today",
    "วันนี้": "today",
    "tomorrow": "tomorrow",
    "tmr": "tomorrow",
    "tmrw": "tomorrow",
    "tomorow": "tomorrow",
    "torrow": "tomorrow",
    "tommorow": "tomorrow",
    "พรุ่งนี้": "tomorrow",
}

_DATE_ISO_RE = re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")
_DATE_SPACED_RE = re.compile(r"\b(20\d{2})\s+(\d{1,2})\s+(\d{1,2})\b")
_DATE_DMY_RE = re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2})\b")
_DATE_COMPACT_RE = re.compile(r"\b(20\d{2})(\d{2})(\d{2})\b")


def _strip_accents(s: str) -> str:
    if not s:
        return s
    return "".join(ch for ch in unicodedata.normalize("NFKD", s) if not unicodedata.combining(ch))


def _normalize_spaces(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


def _to_ascii_digits(s: str) -> str:
    out: List[str] = []
    for ch in (s or ""):
        try:
            if ch.isdigit() and ord(ch) > 127:
                out.append(str(unicodedata.digit(ch)))
            else:
                out.append(ch)
        except Exception:
            out.append(ch)
    return "".join(out)


def basic_sanitize(text: str) -> str:
    t = text or ""
    t = unicodedata.normalize("NFKC", t)
    t = _to_ascii_digits(t)
    t = _strip_accents(t)
    t = _normalize_spaces(t)
    return t


def parse_date(text: str) -> Optional[str]:
    t0 = basic_sanitize(text).lower()
    if not t0:
        return None

    today = local_today_date()

    for w, norm in _DAY_WORDS.items():
        if re.search(rf"\b{re.escape(w)}\b", t0):
            if norm == "today":
                return today.isoformat()
            if norm == "tomorrow":
                return (today + timedelta(days=1)).isoformat()

    m = _DATE_ISO_RE.search(t0)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d.isoformat()
        except Exception:
            return None

    m = _DATE_SPACED_RE.search(t0)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d.isoformat()
        except Exception:
            return None

    m = _DATE_DMY_RE.search(t0)
    if m:
        try:
            d = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
            return d.isoformat()
        except Exception:
            return None

    # Accept compact dates like 20260301 (YYYYMMDD).
    m = _DATE_COMPACT_RE.search(t0)
    if m:
        try:
            d = date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
            return d.isoformat()
        except Exception:
            return None

    return None


def _clean_place_phrase(s: str) -> str:
    s = basic_sanitize(s)
    if not s:
        return ""

    for w in sorted(_DAY_WORDS.keys(), key=len, reverse=True):
        s = re.sub(rf"\b{re.escape(w)}\b", " ", s, flags=re.I)

    s = _DATE_ISO_RE.sub(" ", s)
    s = _DATE_SPACED_RE.sub(" ", s)
    s = _DATE_DMY_RE.sub(" ", s)
    s = _DATE_COMPACT_RE.sub(" ", s)

    # Remove passenger/count words that often trail destinations in one-line requests.
    s = re.sub(r"(tickets?|pax|ppl|people|persons?|person|adult|adults)", " ", s, flags=re.I)
    s = re.sub(r"(คน|ที่นั่ง|ใบ)", " ", s)

    s = re.sub(r"\b\d{1,2}\b", " ", s)
    s = re.sub(r"[|,;]+", " ", s)
    return _normalize_spaces(s).strip()


# Route extraction patterns.
# NOTE: '-' is only allowed as a delimiter when surrounded by spaces.
_FROM_TO_PATTERNS: List[Tuple[re.Pattern, Tuple[int, int]]] = [
    (re.compile(r"^\s*(.+?)\s+to\s+(.+?)\s*$", re.I), (1, 2)),
    (re.compile(r"^\s*from\s+(.+?)\s+to\s+(.+?)\s*$", re.I), (1, 2)),
    (re.compile(r"^\s*(.+?)\s*(->|→)\s*(.+?)\s*$", re.I), (1, 3)),
    (re.compile(r"^\s*(.+?)\s+[-–—]\s+(.+?)\s*$", re.I), (1, 2)),
    (re.compile(r"^\s*จาก\s+(.+?)\s+ไป\s+(.+?)\s*$", re.I), (1, 2)),
    (re.compile(r"^\s*de\s+(.+?)\s+a\s+(.+?)\s*$", re.I), (1, 2)),
]


def extract_from_to(text: str) -> Tuple[Optional[str], Optional[str]]:
    """Extract (from, to) if the user clearly provided a route.

    Guardrails:
    - If the input is date-only, return (None, None).
    """

    t = basic_sanitize(text)
    if not t:
        return None, None

    # Date-only safeguard: a bare date should never be treated as a route.
    if parse_date(t) and _clean_place_phrase(t) == "":
        return None, None

    for pat, (gi, gj) in _FROM_TO_PATTERNS:
        m = pat.search(t)
        if not m:
            continue
        a = _clean_place_phrase(m.group(gi) or "")
        b = _clean_place_phrase(m.group(gj) or "")
        if a and b:
            return a, b
    return None, None
