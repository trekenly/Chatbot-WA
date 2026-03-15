# app/core/orchestrator.py
from __future__ import annotations

import asyncio
import inspect
import json
import re
import time
import unicodedata
from dataclasses import dataclass, field
from datetime import date, timedelta
from difflib import get_close_matches
from typing import Any, Dict, List, Optional, Tuple
from time import perf_counter

from app.core.contracts import Action, ChatResponse
from app.formatters.reservation_card import format_reservation_card, _fmt_amount, _fmt_expiry
from app.utils.dates import local_today_date
from app.utils.env import (
    env_str as _env_str,
    env_int as _env_int,
    env_int_required as _env_int_required,
    env_float as _env_float,
    env_bool as _env_bool,
)

# Parsing lives in a separate module; keep orchestrator focused on state flow.
from app.core.parsing import extract_from_to as extract_from_to
from app.core.parsing import parse_date as parse_date

# ✅ dependency-free multilingual canonical matching
from app.utils.canonical import canonicalize
from app.utils.stop_aliases import iter_alias_targets


# =============================================================================
# Text normalization / commands
# =============================================================================

_CMD_SYNONYMS: Dict[str, str] = {
    # help/meta
    "help": "help",
    "?": "help",
    "show": "show",
    "reset": "reset",
    "restart": "reset",
    "start over": "reset",
    # confirm
    "confirm": "confirm",
    "ok": "confirm",
    "okay": "confirm",
    "yes": "confirm",
    "y": "confirm",
    "ตกลง": "confirm",
    # reserve
    "reserve": "reserve",
    "reservation": "reserve",
    "book": "reserve",
    "booking": "reserve",
    "hold": "reserve",
    "ล็อค": "reserve",
    "จอง": "reserve",
    # pay
    "pay": "pay",
    "payment": "pay",
    "pay now": "pay",
    "checkout": "pay",
    "ชำระ": "pay",
    "จ่าย": "pay",
    # cancel
    "cancel": "cancel",
    "cancel booking": "cancel",
    "ยกเลิก": "cancel",
    # change
    "change": "change",
    "change trip": "change",
    "rebook": "change",
    "เปลี่ยน": "change",
    # status/details
    "status": "status",
    "check": "status",
    "ตรวจสอบ": "status",
    "details": "details",
    "detail": "details",
    "info": "details",
    "payinfo": "payinfo",
}

_DAY_WORDS: Dict[str, str] = {
    "today": "today",
    "tod": "today",
    "วันนี้": "today",
    "tomorrow": "tomorrow",
    "tmr": "tomorrow",
    "tmrw": "tomorrow",
    "tommorow": "tomorrow",
    "พรุ่งนี้": "tomorrow",
}

_ORDINALS: Dict[str, int] = {
    "first": 1,
    "1st": 1,
    "one": 1,
    "second": 2,
    "2nd": 2,
    "two": 2,
    "third": 3,
    "3rd": 3,
    "three": 3,
    "fourth": 4,
    "4th": 4,
    "four": 4,
    "fifth": 5,
    "5th": 5,
    "five": 5,
    "sixth": 6,
    "6th": 6,
    "six": 6,
    "seventh": 7,
    "7th": 7,
    "seven": 7,
    "eighth": 8,
    "8th": 8,
    "eight": 8,
    "ninth": 9,
    "9th": 9,
    "nine": 9,
    "tenth": 10,
    "10th": 10,
    "ten": 10,
}

_SUPPORTED_COMMANDS = {
    "help",
    "show",
    "status",
    "details",
    "payinfo",
    "reset",
    "confirm",
    "reserve",
    "pay",
    "cancel",
    "change",
}

_PROMPT_DATE = "When would you like to travel?"
_PROMPT_PAX = "How many tickets? (e.g. 2 or '2 pax')"
_PROMPT_TO = "Where are you going TO? (type a city/terminal name)"
_PROMPT_FROM = "Where are you departing FROM? (type a city/terminal name)"

# ---------------------------------------------------------------------------
# Friendly place labels for WhatsApp list items (title ≤24, desc ≤72).
# Keys are lowercase substrings to match against keyword_name.
# Values are (short_english_title, thai_name, brief_tagline).
# More-specific keys must appear before generic ones (e.g. "sai tai mai" before "bangkok").
# ---------------------------------------------------------------------------
_PLACE_DISPLAY: Dict[str, Tuple[str, str, str]] = {
    "sai tai mai":          ("Southern Terminal",  "ขนส่งสายใต้ใหม่",  "South Bangkok bus terminal"),
    "southern":             ("Southern Terminal",  "ขนส่งสายใต้ใหม่",  "South Bangkok bus terminal"),
    "ekkamai":              ("Eastern Terminal",   "สถานีเอกมัย",       "East Bangkok bus terminal"),
    "mo chit 2":            ("Northern Terminal",  "หมอชิต 2",          "North Bangkok bus terminal"),
    "chatuchak":            ("Northern Terminal",  "หมอชิต 2",          "North Bangkok bus terminal"),
    "mo chit":              ("Northern Terminal",  "หมอชิต",            "North Bangkok bus terminal"),
    "rangsit":              ("Rangsit Terminal",   "รังสิต",            "North Bangkok, near airport"),
    "bangkok":              ("Bangkok",            "กรุงเทพฯ",          "Capital city, Grand Palace & temples"),
    "phuket":               ("Phuket",             "ภูเก็ต",            "Tropical island, beach resorts"),
    "chiang mai":           ("Chiang Mai",         "เชียงใหม่",         "Northern city, temples & mountains"),
    "chiang rai":           ("Chiang Rai",         "เชียงราย",          "Golden Triangle, White Temple"),
    "surat thani":          ("Surat Thani",        "สุราษฎร์ธานี",      "Gateway to Koh Samui & Phangan"),
    "hua hin":              ("Hua Hin",            "หัวหิน",            "Royal seaside resort town"),
    "pattaya":              ("Pattaya",            "พัทยา",             "Coastal resort city, nightlife"),
    "krabi":                ("Krabi",              "กระบี่",            "Limestone cliffs, island hopping"),
    "koh samui":            ("Koh Samui",          "เกาะสมุย",          "Palm-lined island paradise"),
    "koh phangan":          ("Koh Phangan",        "เกาะพะงัน",         "Full Moon Party island"),
    "koh tao":              ("Koh Tao",            "เกาะเต่า",          "Top diving & snorkelling island"),
    "kanchanaburi":         ("Kanchanaburi",       "กาญจนบุรี",         "WWII history, waterfalls & rivers"),
    "ayutthaya":            ("Ayutthaya",          "อยุธยา",            "Ancient ruins, UNESCO World Heritage"),
    "nakhon ratchasima":    ("Korat",              "โคราช",             "Northeast gateway, Khmer temples"),
    "korat":                ("Korat",              "โคราช",             "Northeast gateway, Khmer temples"),
    "udon thani":           ("Udon Thani",         "อุดรธานี",          "Northeast hub, Bronze Age history"),
    "khon kaen":            ("Khon Kaen",          "ขอนแก่น",           "Northeast university & silk city"),
    "nakhon si thammarat":  ("Nakhon Si Th.",      "นครศรีธรรมราช",     "Southern temples & shadow puppets"),
    "hat yai":              ("Hat Yai",            "หาดใหญ่",           "Southern shopping city near Malaysia"),
    "ranong":               ("Ranong",             "ระนอง",             "Hot springs, Myanmar border crossing"),
    "phang nga":            ("Phang Nga",          "พังงา",             "James Bond Bay, sea caves & karsts"),
    "trang":                ("Trang",              "ตรัง",              "Beaches, caves & dim sum culture"),
    "satun":                ("Satun",              "สตูล",              "Pristine islands, marine park"),
    "chumphon":             ("Chumphon",           "ชุมพร",             "Ferry point to Koh Tao & Koh Samui"),
    "rayong":               ("Rayong",             "ระยอง",             "Eastern seaboard, fruit & beaches"),
}


def _friendly_place_label(name: str, province: str) -> Tuple[str, str]:
    """Return (title ≤24, description ≤72) for a WhatsApp list row.

    Title  = short recognisable English name (fits the 24-char WA title limit).
    Desc   = Thai name · brief tagline (fits the 72-char WA description limit).
    """
    name_l = name.lower()
    for key, (short_en, thai, tagline) in _PLACE_DISPLAY.items():
        if key in name_l:
            title = short_en[:24]
            desc = f"{thai} · {tagline}"
            return title, desc[:72]
    # Fallback: raw name as title, province as hint (no lookup available).
    title = name[:24]
    desc = province[:72] if province and province.lower() not in name.lower() else ""
    return title, desc


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


def _basic_sanitize(text: str) -> str:
    t = text or ""
    t = unicodedata.normalize("NFKC", t)
    t = _to_ascii_digits(t)
    t = _strip_accents(t)
    t = _normalize_spaces(t)
    return t


def _normalize_for_match(s: str) -> str:
    return re.sub(r"\s+", " ", _basic_sanitize(s).lower()).strip()


def _normalize_cmd(raw_text: str) -> str:
    t = _basic_sanitize(raw_text).lower().strip()

    if t in _DAY_WORDS:
        t = _DAY_WORDS[t]

    if t in _CMD_SYNONYMS:
        return _CMD_SYNONYMS[t]

    for k, v in _CMD_SYNONYMS.items():
        if t.startswith(k + " "):
            return v

    close = get_close_matches(t, list(_SUPPORTED_COMMANDS), n=1, cutoff=0.84)
    if close:
        return close[0]

    return t


def _suggest_command(user_text: str) -> Optional[str]:
    t = _basic_sanitize(user_text).lower()
    if not t:
        return None
    close = get_close_matches(t, list(_SUPPORTED_COMMANDS), n=1, cutoff=0.78)
    return close[0] if close else None


# =============================================================================
# Parsers
# =============================================================================

_DATE_ISO_RE = re.compile(r"\b(20\d{2})[-/](\d{1,2})[-/](\d{1,2})\b")
_DATE_SPACED_RE = re.compile(r"\b(20\d{2})\s+(\d{1,2})\s+(\d{1,2})\b")
_DATE_DMY_RE = re.compile(r"\b(\d{1,2})[-/](\d{1,2})[-/](20\d{2})\b")

_PAX_PLAIN_RE = re.compile(r"^\d{1,2}$")
_PAX_LABELED_RE = re.compile(r"\b(\d{1,2})\s*(tickets?|pax|people|persons?|ppl|adults?)\b", re.I)

_SEATISH_MULTI_TOKEN_RE = re.compile(
    r"^\s*([A-Z]?\d{1,3}[A-Z]?)([,\s]+([A-Z]?\d{1,3}[A-Z]?))+\s*$",
    re.I,
)


def parse_pax(text: str) -> Optional[int]:
    t = _basic_sanitize(text)
    if not t:
        return None

    if _SEATISH_MULTI_TOKEN_RE.match(t):
        return None

    tl = t.lower()

    if _PAX_PLAIN_RE.fullmatch(tl):
        n = int(tl)
        return n if 1 <= n <= 20 else None

    m = _PAX_LABELED_RE.search(tl)
    if m:
        n = int(m.group(1))
        return n if 1 <= n <= 20 else None

    # If user typed a date + one number, don't misread day/month as pax
    t2 = _DATE_ISO_RE.sub(" ", tl)
    t2 = _DATE_SPACED_RE.sub(" ", t2)
    t2 = _DATE_DMY_RE.sub(" ", t2).strip()
    nums = re.findall(r"\b(\d{1,2})\b", t2)
    if len(nums) == 1:
        n = int(nums[0])
        return n if 1 <= n <= 20 else None

    return None


def parse_choice_index(text: str) -> Optional[int]:
    t = _basic_sanitize(text).lower().strip()
    if not t:
        return None

    if t in _ORDINALS:
        return _ORDINALS[t]

    m = re.search(r"\b(\d{1,2})\b", t)
    if not m:
        return None
    try:
        return int(m.group(1))
    except Exception:
        return None


def parse_seats(text: str) -> List[str]:
    t = _basic_sanitize(text).upper()
    t = t.replace("，", ",").replace("、", ",").replace(";", ",")
    tokens = re.split(r"[,\s]+", t.strip())

    out: List[str] = []
    seen = set()
    for tok in tokens:
        tok = tok.strip()
        if not tok:
            continue
        if re.match(r"^[A-Z]?\d{1,3}[A-Z]?$", tok):
            if tok not in seen:
                seen.add(tok)
                out.append(tok)
    return out


def _clean_place_phrase(s: str) -> str:
    s = _basic_sanitize(s)
    if not s:
        return ""

    for w in sorted(_DAY_WORDS.keys(), key=len, reverse=True):
        s = re.sub(rf"\b{re.escape(w)}\b", " ", s, flags=re.I)

    s = _DATE_ISO_RE.sub(" ", s)
    s = _DATE_SPACED_RE.sub(" ", s)
    s = _DATE_DMY_RE.sub(" ", s)

    s = _PAX_LABELED_RE.sub(" ", s)
    s = re.sub(r"\b\d{1,2}\b", " ", s)
    s = re.sub(r"[|,;]+", " ", s)

    return _normalize_spaces(s).strip()


# =============================================================================
# Generic helpers
# =============================================================================


def _safe_get(d: Any, path: List[str], default: Any = "") -> Any:
    cur: Any = d
    for k in path:
        if isinstance(cur, list):
            try:
                idx = int(k)
                cur = cur[idx]
            except Exception:
                return default
        elif isinstance(cur, dict):
            cur = cur.get(k)
        else:
            return default
    return cur if cur is not None else default


def _extract_http_error_details(exc: Exception) -> Tuple[Optional[int], Optional[str]]:
    status_code = None
    body_text = None
    resp = getattr(exc, "response", None)

    try:
        status_code = getattr(resp, "status_code", None)
    except Exception:
        status_code = None

    try:
        body_text = getattr(resp, "text", None)
        if not body_text:
            content = getattr(resp, "content", None)
            if isinstance(content, (bytes, bytearray)):
                body_text = content.decode("utf-8", errors="replace")
            elif isinstance(content, str):
                body_text = content
    except Exception:
        body_text = None

    return status_code, body_text


def _dbg_exc(e: Exception) -> str:
    sc, body = _extract_http_error_details(e)
    dbg = f"{type(e).__name__}: {e}"
    if sc is not None:
        dbg += f" | status_code={sc}"
    if body:
        dbg += f" | response={body}"
    return dbg


def _looks_like_busx_no_data(e: Exception) -> bool:
    s = f"{e}"
    if "1007" in s and ("No data" in s or "no data" in s):
        return True
    sc, body = _extract_http_error_details(e)
    if sc == 400 and body and ("1007" in body) and ("No data" in body or "no data" in body):
        return True
    return False


def _busx_error_code_from_text(text: str) -> Optional[str]:
    if not text:
        return None
    m = re.search(r"\bcode\s*[:=]\s*(\d{3,5})\b", text, re.I)
    if m:
        return m.group(1)
    m = re.search(r'"code"\s*:\s*(\d{3,5})', text)
    if m:
        return m.group(1)
    return None


def _exception_busx_code(e: Exception) -> Optional[str]:
    s = str(e) or ""
    code = _busx_error_code_from_text(s)
    if code:
        return code
    _sc, body = _extract_http_error_details(e)
    if body:
        code = _busx_error_code_from_text(body)
        if code:
            return code
    return None


def _call_kwargs_accepted(fn: Any, kwargs: Dict[str, Any]) -> Dict[str, Any]:
    """Filter kwargs to match function signature (unless **kwargs present)."""
    try:
        sig = inspect.signature(fn)
        params = list(sig.parameters.values())
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
            return kwargs
        accepted = {p.name for p in params}
        return {k: v for k, v in kwargs.items() if k in accepted}
    except Exception:
        return kwargs


async def _call_async_method_safe(obj: Any, method_name: str, **kwargs) -> Any:
    fn = getattr(obj, method_name, None)
    if not fn:
        return None
    safe_kwargs = _call_kwargs_accepted(fn, kwargs)
    return await fn(**safe_kwargs)


def _json_preview(obj: Any, max_chars: int = 6000) -> str:
    try:
        txt = json.dumps(obj, ensure_ascii=False, indent=2)
    except Exception:
        txt = str(obj)

    if not isinstance(txt, str):
        txt = str(txt)

    if len(txt) <= max_chars:
        return txt

    head_n = max_chars // 2
    tail_n = max_chars - head_n
    return txt[:head_n] + "\n...\n(TRUNCATED)\n...\n" + txt[-tail_n:]


def _say_with_choices(*, intro: str, title: str, options: List[Dict[str, Any]]) -> List[Action]:
    # UI is driven by choose_one; keep chat text short.
    return [
        Action(type="say", payload={"text": (intro or "").strip()}),
        Action(type="choose_one", payload={"title": title, "options": options}),
    ]


def _iso_hhmm(iso_dt: str) -> str:
    try:
        if "T" in iso_dt:
            tpart = iso_dt.split("T", 1)[1]
            hhmm = tpart[:5]
            if re.match(r"^\d{2}:\d{2}$", hhmm):
                return hhmm
        return ""
    except Exception:
        return ""




def _unique_passenger_name(base: str, idx: int, pax: int) -> str:
    base = (base or "Passenger").strip()
    if pax <= 1:
        return base
    suffix = chr(ord("A") + idx) if idx < 26 else str(idx + 1)
    return f"{base} {suffix}"


def _looks_like_default_details(s: "SessionState") -> bool:
    """Heuristic: if details still look like canned defaults, treat as missing."""
    try:
        # explicit flag wins
        if not getattr(s, "details_collected", False):
            return True

        default_email = (s.passenger_email or "").strip().lower() == "test@example.com"
        default_phone = (s.passenger_phone_number or "").strip() in {"0000000000", "000000000"}
        default_name = (s.passenger_name or "").strip().lower() in {"test", ""} or (
            (s.contact_name or "").strip().lower() in {"test user", ""}
        )
        return default_email or default_phone or default_name
    except Exception:
        return True



# =============================================================================
# Trip extraction / formatting
# =============================================================================



def _looks_like_trip_obj(obj: Any) -> bool:
    """Heuristic check for a single BusX trip object.

    The BusX search_trips response is not always returned as a list. Some routes
    come back as a single dict under data.departure. The workbook for search_trips
    documents many fields that can identify a valid trip object, so the detector
    should accept the common documented keys instead of only a narrow subset.
    """
    if not isinstance(obj, dict):
        return False
    direct_keys = {
        # Common identifiers / timestamps
        "trip_id", "trip_ref_id", "trip_number", "trip_time", "trip_time_zone",
        "reservation_cutoff_time",
        # Availability / fares
        "fare", "fare_ref_id", "fare_type", "inventory", "seat_available",
        "price", "cabin_class",
        # Route / operator metadata
        "route", "carrier", "operating_carrier", "vehicle", "amenity_group",
        # Boarding / dropoff structures in the API workbook
        "boarding", "dropoff", "departure_time", "arrival_time",
        "boarding_time", "dropping_time",
        # Misc trip markers
        "service_group", "seating_required", "is_active",
    }
    if any(k in obj for k in direct_keys):
        return True
    route = obj.get("route")
    if isinstance(route, dict) and any(k in route for k in ("departure", "arrival", "from", "to", "route_id", "route_name")):
        return True
    boarding = obj.get("boarding")
    dropoff = obj.get("dropoff")
    if isinstance(boarding, dict) and isinstance(dropoff, dict):
        return True
    return False


def _coerce_trip_list(value: Any) -> List[Dict[str, Any]]:
    """Normalize a BusX trip payload into a list of trip dicts."""
    if isinstance(value, list):
        return [x for x in value if isinstance(x, dict)]
    if _looks_like_trip_obj(value):
        return [value]
    if isinstance(value, dict):
        # Common wrappers for single-trip or nested-trip payloads.
        for key in ("departure", "departures", "trips", "trip", "results", "items"):
            if key in value:
                found = _coerce_trip_list(value.get(key))
                if found:
                    return found
        # Last resort: scan nested values for the first trip-shaped payload.
        for nested in value.values():
            found = _coerce_trip_list(nested)
            if found:
                return found
    return []


def extract_trips(resp: Any) -> List[Dict[str, Any]]:
    """Extract trips from BusX search responses.

    Handles both the usual list responses and single-trip dict responses.
    """
    if isinstance(resp, dict):
        data = resp.get("data")
        found = _coerce_trip_list(data)
        if found:
            return found
        found = _coerce_trip_list(resp.get("trips"))
        if found:
            return found
        found = _coerce_trip_list(resp.get("departure"))
        if found:
            return found
    return _coerce_trip_list(resp)



def _summarize_probe_response(resp: Any) -> Dict[str, Any]:
    """Small, safe summary for DIAG logs when route probing looks empty.

    We intentionally log shapes, types, and key names only  -  not full payloads.
    """
    out: Dict[str, Any] = {"type": type(resp).__name__}
    if isinstance(resp, dict):
        out["keys"] = sorted(list(resp.keys()))[:20]
        data = resp.get("data")
        out["success"] = resp.get("success")
        out["message"] = resp.get("message")
        out["data_type"] = type(data).__name__
        if isinstance(data, dict):
            out["data_keys"] = sorted(list(data.keys()))[:20]
            dep = data.get("departure")
            out["departure_type"] = type(dep).__name__
            if isinstance(dep, dict):
                out["departure_keys"] = sorted(list(dep.keys()))[:25]
                # One more level for common nested shapes.
                for key in ("trips", "trip", "items", "results", "route", "boarding", "dropoff"):
                    nested = dep.get(key)
                    if isinstance(nested, dict):
                        out[f"departure_{key}_keys"] = sorted(list(nested.keys()))[:20]
                    elif isinstance(nested, list):
                        out[f"departure_{key}_len"] = len(nested)
            elif isinstance(dep, list):
                out["departure_len"] = len(dep)
    return out


def format_trip_option(trip: Dict[str, Any], idx: int, pax: int, currency: str) -> Dict[str, Any]:
    dep_iso = str(_safe_get(trip, ["route", "departure", "departure_time"], "") or "")
    arr_iso = str(_safe_get(trip, ["route", "arrival", "arrival_time"], "") or "")
    dep = _iso_hhmm(dep_iso)
    arr = _iso_hhmm(arr_iso)

    # Day-offset label (next day / +2 days / etc.)
    try:
        dep_d = date.fromisoformat(dep_iso.split("T")[0])
        arr_d = date.fromisoformat(arr_iso.split("T")[0])
        delta = (arr_d - dep_d).days
        day_tag = " (next day)" if delta == 1 else (f" (+{delta} days)" if delta > 1 else "")
    except Exception:
        day_tag = ""

    # Title ≤ 24 chars: departure → arrival time only (no day tag — kept for description)
    title_raw = f"{dep} → {arr}" if dep and arr else (dep or arr or "?")
    title = title_raw[:24]

    # Fare data
    fare_type0 = (trip.get("fare_type") or [{}])[0] if isinstance(trip.get("fare_type"), list) else {}
    fare_ref_id = str(fare_type0.get("fare_ref_id") or "")
    fare0 = (fare_type0.get("fare") or [{}])[0] if isinstance(fare_type0.get("fare"), list) else {}
    price_obj = fare0.get("price") if isinstance(fare0.get("price"), dict) else {}
    unit_price = price_obj.get("price") or price_obj.get("base_price")
    try:
        unit: Optional[float] = float(unit_price) if unit_price is not None else None
    except Exception:
        unit = None

    carrier = str(_safe_get(trip, ["carrier", "carrier_name"], "") or "Bus")
    cabin = str(_safe_get(trip, ["cabin_class", "cabin_class_name"], "") or "")
    seats = _safe_get(trip, ["inventory", "seat_available"], "")

    # Price string — compact, shows total when >1 pax
    if unit is not None:
        price_str = f"฿{int(unit) if unit == int(unit) else unit:.0f}"
        if pax > 1:
            price_str += f" (฿{int(unit * pax)} total)"
    else:
        price_str = ""

    # Seats urgency hint
    try:
        seat_n = int(seats)
        seat_part = f" · {seat_n} left" if seat_n <= 5 else ""
    except Exception:
        seat_part = ""

    # Cabin label — skip generic values
    cabin_clean = cabin.strip()
    cabin_part = f" {cabin_clean} ·" if cabin_clean and cabin_clean.lower() not in {"bus", "standard", ""} else ""

    # Description ≤ 72 chars: Carrier · Cabin · Price · Day tag · Seats
    carrier_short = carrier[:20]
    day_str = f" · {day_tag.strip()}" if day_tag else ""
    price_part = f" · {price_str}" if price_str else ""
    desc_raw = f"{carrier_short}{cabin_part}{price_part}{day_str}{seat_part}"
    desc = desc_raw[:72]

    return {"id": str(idx), "label": title, "description": desc, "fare_ref_id": fare_ref_id}


def _extract_departure_ref_id_any(obj: Any) -> Optional[str]:
    """Deep scan for departure ref/id-like fields."""
    if obj is None:
        return None

    if isinstance(obj, dict):
        for k in (
            "departure_ref_id",
            "departureRefId",
            "departure_reference_id",
            "departureReferenceId",
            "departure_id",
            "departureId",
            "checkout_departure_ref_id",
            "checkoutDepartureRefId",
        ):
            v = obj.get(k)
            if v is not None and str(v).strip():
                return str(v).strip()

    def walk(x: Any):
        if isinstance(x, dict):
            for k, v in x.items():
                yield k, v
                yield from walk(v)
        elif isinstance(x, list):
            for v in x[:400]:
                yield from walk(v)

    for k, v in walk(obj):
        lk = str(k).lower()
        if "departure" in lk and ("ref" in lk or lk.endswith("id") or lk.endswith("_id")):
            if v is not None and str(v).strip():
                return str(v).strip()

    return None


def _candidate_departure_ref_ids(s: "SessionState") -> List[str]:
    """
    Candidates to try for departure_ref_id.
    The real one comes from create_checkouts() on the current wrapper.
    """
    cand: List[str] = []

    def add(v: Any) -> None:
        if v is None:
            return
        sv = str(v).strip()
        if not sv:
            return
        if sv not in cand:
            cand.append(sv)

    trip = s.selected_trip or {}

    add(s.departure_ref_id)
    add(_extract_departure_ref_id_any(trip))
    add(_extract_departure_ref_id_any(s.last_seat_layout))
    add(_extract_departure_ref_id_any(s.mark_seats_results))
    add(_extract_departure_ref_id_any(s.checkout_response))

    add(s.selected_trip_id)
    add(s.selected_fare_ref_id)

    add(_safe_get(trip, ["route", "route_id"], ""))
    add(_safe_get(trip, ["route", "route_code"], ""))
    add(_safe_get(trip, ["route", "departure", "stop_id"], ""))
    add(_safe_get(trip, ["route", "arrival", "stop_id"], ""))
    add(_safe_get(trip, ["trip_number"], ""))
    add(_safe_get(trip, ["trip_time"], ""))

    return cand


# =============================================================================
# Seat extraction
# =============================================================================


def extract_seats_from_layout(resp: Any) -> List[str]:
    out: List[str] = []
    if not isinstance(resp, dict):
        return out
    data = resp.get("data")
    if not isinstance(data, dict):
        return out

    details = data.get("seat_layout_details")
    if isinstance(details, list):
        for cell in details:
            if not isinstance(cell, dict):
                continue
            if (cell.get("object_code") or "").lower() != "seat":
                continue
            seat_obj = cell.get("object_code_seat")
            if not isinstance(seat_obj, dict):
                continue
            seat_no = seat_obj.get("seat_number")
            status = (seat_obj.get("seat_status") or "").lower().strip()
            if seat_no and status == "available":
                out.append(str(seat_no))
    return out


# =============================================================================
# Payment extraction helpers (details/payinfo)
# =============================================================================


def _extract_payment_block(reservation_like: Any) -> Dict[str, Optional[str]]:
    out: Dict[str, Optional[str]] = {
        "order_ref_id": None,
        "paycode": None,
        "payment_required": None,
        "total_price": None,
        "currency": None,
        "payment_status": None,
        "expires_at": None,
    }

    if not isinstance(reservation_like, dict):
        return out

    data = reservation_like.get("data")
    if not isinstance(data, dict):
        return out

    order = data.get("order")
    if not isinstance(order, dict):
        return out

    out["order_ref_id"] = str(order.get("order_ref_id") or "") or None
    out["paycode"] = str(order.get("paycode") or "") or None
    out["payment_required"] = str(order.get("payment_required") or "") or None

    payment = order.get("payment")
    if isinstance(payment, dict):
        out["total_price"] = str(payment.get("total_price") or "") or None
        out["currency"] = str(payment.get("currency") or "") or None
        out["payment_status"] = str(payment.get("payment_status") or "") or None
        out["expires_at"] = str(payment.get("expires_at") or "") or None

    return out


def _find_payment_hints(obj: Any) -> Dict[str, str]:
    wanted_keys = {
        "payment_url",
        "url",
        "redirect_url",
        "checkout_url",
        "qrcode",
        "qr_code",
        "qr",
        "barcode",
        "bar_code",
        "paycode",
        "payment_code",
        "reference",
        "reference_no",
        "ref",
        "ref1",
        "ref2",
        "ref3",
        "instruction",
        "instructions",
        "note",
        "notes",
        "provider",
        "payment_provider",
        "channel",
        "method",
    }

    found: Dict[str, str] = {}

    def walk(x: Any, path: str) -> None:
        if len(found) >= 30:
            return
        if isinstance(x, dict):
            for k, v in x.items():
                kp = f"{path}.{k}" if path else str(k)
                lk = str(k).lower()
                if lk in wanted_keys:
                    if isinstance(v, (str, int, float)) and str(v).strip():
                        found[kp] = str(v)
                walk(v, kp)
        elif isinstance(x, list):
            for i, v in enumerate(x[:50]):
                walk(v, f"{path}[{i}]")

    walk(obj, "")
    return found


# =============================================================================
# Session state
# =============================================================================


@dataclass
class SessionState:
    step: str = "NEW"

    desired_from_text: Optional[str] = None
    desired_to_text: Optional[str] = None

    from_query: Optional[str] = None
    to_query: Optional[str] = None
    from_keyword_id: Optional[int] = None
    to_keyword_id: Optional[int] = None
    from_label: Optional[str] = None
    to_label: Optional[str] = None

    pending_from_candidates: List[Dict[str, Any]] = field(default_factory=list)
    pending_to_candidates: List[Dict[str, Any]] = field(default_factory=list)
    awaiting_choice: Optional[str] = None  # "from" | "to" | None

    pending_to_map_by_from_id: Dict[int, List[Dict[str, Any]]] = field(default_factory=dict)
    viable_from_alternatives: List[Dict[str, Any]] = field(default_factory=list)

    departure_date: Optional[str] = None
    pax: Optional[int] = None

    trips: List[Dict[str, Any]] = field(default_factory=list)
    selected_trip: Optional[Dict[str, Any]] = None
    selected_fare_ref_id: Optional[str] = None
    selected_trip_id: Optional[str] = None
    selected_index: Optional[int] = None

    departure_ref_id: Optional[str] = None
    checkout_response: Any = None

    seat_layouts: Dict[str, Any] = field(default_factory=dict)
    last_seat_layout: Any = None
    available_seats: List[str] = field(default_factory=list)
    selected_seats: List[str] = field(default_factory=list)
    seat_event_ids: List[str] = field(default_factory=list)

    reservation_id: Optional[str] = None
    order_ref_id: Optional[str] = None
    mark_seats_results: Any = None
    busx_reservation_response: Any = None
    busx_payment_response: Any = None

    # Passenger/contact capture (collected via UI form before reservation)
    details_collected: bool = False
    last_hold_message: Optional[str] = None

    passenger_title_id: int = 1
    passenger_name: str = "Test"
    passenger_last_name: str = "User"
    passenger_email: str = "test@example.com"
    passenger_phone_country: str = "TH"
    passenger_phone_number: str = "0000000000"
    passenger_type_code: str = "ADT"
    gender: str = "M"
    seat_floor: int = 1

    contact_title_id: int = 1
    contact_name: str = "Test User"
    contact_phone_country_code: str = "TH"
    contact_phone_number: str = "0000000000"
    contact_email: str = "test@example.com"

    time_zone: str = "Asia/Bangkok"
    locale: Optional[str] = None
    currency: Optional[str] = None

    # Pipeline-injected conversation language (e.g. "th", "zh").
    # Used by format_reservation_card for locale-aware route display.
    chat_language: Optional[str] = None

    # Set to True after the welcome message has been shown so it is never
    # repeated mid-session (only reset clears this back to False).
    welcomed: bool = False


# =============================================================================
# Orchestrator
# =============================================================================


class Orchestrator:
    """
    Efficiency-focused rewrite:
    - Cleaner UI: no duplicated numbered lists (choose_one menu is the source of truth).
    - Less repeated parsing and sanitization.
    - Centralized debug formatting.
    - Kept behavior + BusX integration intact.
    """

    def __init__(self, busx_client: Any):
        self.busx = busx_client
        self.sessions: Dict[str, SessionState] = {}
        self._locks: Dict[str, asyncio.Lock] = {}

        self.default_locale = _env_str("DEFAULT_LOCALE", "en_US")
        self.default_currency = _env_str("DEFAULT_CURRENCY", "THB")
        self.default_from_keyword_id = _env_int_required("DEFAULT_FROM_KEYWORD_ID")
        self.default_from_keyword_name = _env_str("DEFAULT_FROM_KEYWORD_NAME", "Bangkok")
        self.default_to_keyword_id = _env_int_required("DEFAULT_TO_KEYWORD_ID")

        self.auto_reserve_after_seats = _env_bool("AUTO_RESERVE_AFTER_SEATS", True)
        self.soft_guidance = _env_bool("SOFT_GUIDANCE", True)

        self.route_probe_limit = _env_int("ROUTE_PROBE_LIMIT", 10)
        self.route_probe_days = _env_int("ROUTE_PROBE_DAYS", 2)
        self.keyword_cache_ttl_sec = _env_int("KEYWORD_CACHE_TTL_SEC", 600)
        self.busx_call_timeout_sec = _env_int("BUSX_CALL_TIMEOUT_SEC", 8)
        self.checkout_depref_max_attempts = _env_int("CHECKOUT_DEPREF_MAX_ATTEMPTS", 12)

        # behavior knobs
        self.strict_sellable_only = _env_bool("STRICT_SELLABLE_ONLY", True)
        self.strict_probe_budget = _env_int("STRICT_PROBE_BUDGET", max(60, int(self.route_probe_limit or 10) * 8))

        # canonical knobs (optional env overrides)
        self.canon_min_score = _env_float("CANON_MIN_SCORE", 0.35)
        self.canon_top_k = _env_int("CANON_TOP_K", 10)
        self.canon_strict_top_k = _env_int("CANON_STRICT_TOP_K", 50)

        # Temporary diagnostic switch. Keep this off in normal use and enable it
        # only while tracing one failing route-selection flow.
        self.diag_enabled = _env_bool("BUSX_DIAG", False)

        self._cache_route: Dict[Any, Any] = {}
        self._cache_from: Dict[Any, Any] = {}
        self._cache_to: Dict[Any, Any] = {}

    def _diag(self, *parts: Any) -> None:
        """
        Temporary console logger used to trace route-selection state.
        Kept intentionally simple so it cannot affect the active webhook route.
        """
        if not self.diag_enabled:
            return
        try:
            print("DIAG", *parts, flush=True)
        except Exception:
            pass

    def _diag_state(self, s: SessionState) -> Dict[str, Any]:
        """Small, readable slice of session state for debugging."""
        return {
            "step": s.step,
            "awaiting_choice": s.awaiting_choice,
            "desired_from_text": s.desired_from_text,
            "desired_to_text": s.desired_to_text,
            "from_keyword_id": s.from_keyword_id,
            "from_label": s.from_label,
            "to_keyword_id": s.to_keyword_id,
            "to_label": s.to_label,
            "departure_date": s.departure_date,
            "pending_from_candidates": len(s.pending_from_candidates or []),
            "pending_to_candidates": len(s.pending_to_candidates or []),
            "pending_to_map_keys": sorted(list((s.pending_to_map_by_from_id or {}).keys())),
        }

    # -------------------------------------------------------------------------
    # Session utilities
    # -------------------------------------------------------------------------

    def _lock_for(self, user_id: str) -> asyncio.Lock:
        lk = self._locks.get(user_id)
        if lk is None:
            lk = asyncio.Lock()
            self._locks[user_id] = lk
        return lk

    def _get(self, user_id: str) -> SessionState:
        if user_id not in self.sessions:
            s = SessionState()
            # Pre-apply the default departure city so the destinations list can
            # be shown immediately once the user has picked a travel date.
            if self.default_from_keyword_id:
                s.from_keyword_id = self.default_from_keyword_id
            self.sessions[user_id] = s
        return self.sessions[user_id]

    def _locale(self, s: SessionState) -> str:
        return (s.locale or self.default_locale).strip() or self.default_locale

    def _currency(self, s: SessionState) -> str:
        return (s.currency or self.default_currency).strip() or self.default_currency

    def _say(self, s: SessionState, text: str) -> ChatResponse:
        return ChatResponse(actions=[Action(type="say", payload={"text": text})], state=s.__dict__)

    def _say_with_booking_buttons(self, s: SessionState, text: str) -> ChatResponse:
        """Send text with Pay / Cancel / Change reply buttons."""
        return ChatResponse(
            actions=[
                Action(type="say", payload={"text": text}),
                Action(type="choose_one", payload={
                    "title": "What would you like to do?",
                    "options": [
                        {"id": "pay",    "label": "💳 Pay now"},
                        {"id": "cancel", "label": "❌ Cancel"},
                        {"id": "change", "label": "🔄 Change trip"},
                    ],
                }),
            ],
            state=s.__dict__,
        )

    def _ask(self, s: SessionState, field: str, prompt: str) -> ChatResponse:
        return ChatResponse(actions=[Action(type="ask", payload={"field": field, "prompt": prompt})], state=s.__dict__)

    def _welcome_response(self, s: SessionState) -> ChatResponse:
        """Welcome message shown on first contact and after every reset.

        Leads with a short multi-script greeting to immediately signal that the
        bot understands many languages, then opens the date picker so the user's
        first interaction is a tap — not typing.
        """
        s.welcomed = True
        greeting = (
            "Welcome  ·  ยินดีต้อนรับ  ·  欢迎  ·  환영합니다  ·  Bienvenido\n\n"
            "Book bus tickets across Thailand 🇹🇭\n"
            "Chat naturally — I understand English, Thai, Chinese, Korean, "
            "Japanese, Indonesian, Malay, French, Spanish, Russian and more.\n\n"
            "When would you like to travel?"
        )
        return ChatResponse(
            actions=[Action(type="ask", payload={"field": "departure_date", "prompt": greeting})],
            state=s.__dict__,
        )

    async def _await_busx(self, coro, *, timeout: Optional[float] = None) -> Any:
        t = float(timeout if timeout is not None else (self.busx_call_timeout_sec or 0))
        if t <= 0:
            return await coro
        try:
            return await asyncio.wait_for(coro, timeout=t)
        except asyncio.TimeoutError as e:
            raise RuntimeError(f"BusX call timed out after {t:.0f}s") from e

    def _reset_after_new_trip_selected(self, s: SessionState) -> None:
        s.available_seats = []
        s.selected_seats = []
        s.seat_event_ids = []
        s.mark_seats_results = None
        s.checkout_response = None
        s.departure_ref_id = None
        s.reservation_id = None
        s.order_ref_id = None
        s.busx_reservation_response = None
        s.busx_payment_response = None

    # -------------------------------------------------------------------------
    # One-line ingest
    # -------------------------------------------------------------------------

    def _ingest_freeform_line(self, s: SessionState, text: str) -> None:
        raw = text or ""
        if not raw.strip():
            return

        if s.awaiting_choice in {"from", "to"}:
            return
        if s.step in {"PICK_TRIP", "PICK_SEATS"}:
            return

        if not s.departure_date:
            d = parse_date(raw)
            if d:
                s.departure_date = d

        if not s.pax:
            p = parse_pax(raw)
            if p:
                s.pax = p

        if not s.desired_from_text or not s.desired_to_text:
            f, t = extract_from_to(raw)
            if f and t:
                s.desired_from_text = s.desired_from_text or f
                s.desired_to_text = s.desired_to_text or t
                s.from_query = s.from_query or f
                s.to_query = s.to_query or t

    # -------------------------------------------------------------------------
    # Canonical matching helpers
    # -------------------------------------------------------------------------

    def _canonical_match_rows(self, rows: List[Dict[str, Any]], query: str, *, top_k: int) -> List[Dict[str, Any]]:
        if not query or not rows:
            return []

        variants = list(iter_alias_targets(query))
        variants.append(query)

        by_id: Dict[int, Dict[str, Any]] = {}
        for r in rows:
            try:
                by_id[int(r.get("keyword_id"))] = r
            except Exception:
                continue

        best: Dict[int, float] = {}

        for i, q in enumerate(variants):
            is_alias_variant = i < (len(variants) - 1)
            bonus = 0.06 if is_alias_variant else 0.0

            cands = canonicalize(q, rows, top_k=max(top_k, 12), min_score=self.canon_min_score)
            for c in cands:
                try:
                    kid = int(c.keyword_id)
                except Exception:
                    continue
                score = float(c.score) + bonus
                prev = best.get(kid)
                if prev is None or score > prev:
                    best[kid] = score

        if not best:
            return []

        ordered_ids = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
        out: List[Dict[str, Any]] = []
        for kid, _score in ordered_ids[:top_k]:
            r = by_id.get(kid)
            if r is not None:
                out.append(r)
        return out

    # -------------------------------------------------------------------------
    # Cache helpers
    # -------------------------------------------------------------------------

    def _now(self) -> float:
        return time.time()

    def _cache_get(self, cache: dict, key: Any) -> Optional[Any]:
        hit = cache.get(key)
        if not hit:
            return None
        ts, val = hit
        if (self._now() - ts) > self.keyword_cache_ttl_sec:
            return None
        return val

    def _cache_set(self, cache: dict, key: Any, val: Any) -> None:
        cache[key] = (self._now(), val)

    def _probe_dates(self, s: SessionState, *, extra_days: int = 0) -> List[str]:
        base = local_today_date()
        if s.departure_date:
            dates = [s.departure_date]
            # Optionally extend with nearby dates so route-existence probes are not
            # fooled by a single date with no availability.
            if extra_days > 0:
                seen = {s.departure_date}
                dep = base
                try:
                    from datetime import date as _dc
                    dep = _dc.fromisoformat(s.departure_date)
                except Exception:
                    pass
                for delta in range(1, extra_days + 1):
                    for d in [(dep + timedelta(days=delta)).isoformat(),
                               (dep - timedelta(days=delta)).isoformat()]:
                        if d not in seen:
                            seen.add(d)
                            dates.append(d)
            return dates
        n = max(1, int(self.route_probe_days or 1))
        return [(base + timedelta(days=i)).isoformat() for i in range(n)]

    async def _route_has_trips(self, s: SessionState, from_id: int, to_id: int, *, extra_probe_days: int = 0) -> bool:
        dates = self._probe_dates(s, extra_days=extra_probe_days)
        self._diag("route_has_trips:start", {"from_id": int(from_id), "to_id": int(to_id), "dates": dates})
        loc = self._locale(s)
        cur = self._currency(s)

        cache_key_base = (loc, cur, int(from_id), int(to_id))
        cache = self._cache_route

        # When probing with extra dates we require at least one date to have REAL trips
        # before accepting a success:True / empty-trips response.  This prevents the
        # terminal picker from showing terminals whose routes don't actually exist
        # (BusX returns success:True with empty data for both "no trips today" and
        # "route doesn't exist").
        found_real_trips = False
        success_true_no_trips = False  # fallback signal from at least one date

        for d in dates:
            key = (*cache_key_base, d)
            cached = self._cache_get(cache, key)
            if cached is not None:
                self._diag("route_has_trips:cache", {"from_id": int(from_id), "to_id": int(to_id), "date": d, "ok": bool(cached)})
                if cached:
                    if extra_probe_days == 0:
                        return True
                    found_real_trips = True
                continue

            try:
                self._diag("route_has_trips:probe", {"from_id": int(from_id), "to_id": int(to_id), "date": d})
                resp = await self._await_busx(
                    self.busx.search_trips(
                        journey_type="OW",
                        departure_date=d,
                        from_keyword_id=int(from_id),
                        to_keyword_id=int(to_id),
                        currency=cur,
                        locale=loc,
                    )
                )
                trips = extract_trips(resp)
                ok = bool(trips)
                if ok:
                    found_real_trips = True
                elif isinstance(resp, dict) and resp.get("success") is True:
                    # API returned success but no trips — could be "no availability on
                    # this date" (route valid) or "route doesn't exist" (both look the
                    # same).  Record this signal; only accept it if extra_probe_days==0
                    # (single-date probe where we have no other evidence).
                    success_true_no_trips = True
                self._diag("route_has_trips:result", {"from_id": int(from_id), "to_id": int(to_id), "date": d, "ok": ok, "trip_count": len(trips or [])})
                if not ok:
                    self._diag("route_has_trips:raw_summary", {"from_id": int(from_id), "to_id": int(to_id), "date": d, "summary": _summarize_probe_response(resp)})
                self._cache_set(cache, key, ok)
                if ok and extra_probe_days == 0:
                    return True
            except Exception as e:
                self._diag("route_has_trips:error", {"from_id": int(from_id), "to_id": int(to_id), "date": d, "error": _dbg_exc(e)})
                if _looks_like_busx_no_data(e):
                    self._cache_set(cache, key, False)
                continue

        if extra_probe_days > 0:
            # Multi-date probe: only trust real trips as evidence; ignore success_true_no_trips
            # across all dates because we can't distinguish "no availability" from "no route".
            return found_real_trips

        # Single-date probe (original behaviour): accept success:True / no trips as
        # "route valid but nothing available on this date".
        if success_true_no_trips:
            return True
        return False

    # -------------------------------------------------------------------------
    # Keyword fetch (cached)
    # -------------------------------------------------------------------------

    def _keyword_rows(self, resp: Any) -> List[Dict[str, Any]]:
        if isinstance(resp, dict):
            data = resp.get("data")
            if isinstance(data, list):
                return [x for x in data if isinstance(x, dict)]
            if isinstance(data, dict) and isinstance(data.get("data"), list):
                return [x for x in data["data"] if isinstance(x, dict)]
        return []

    async def _list_keyword_from_cached(self, s: SessionState) -> List[Dict[str, Any]]:
        loc = self._locale(s)
        cache = self._cache_from
        cached = self._cache_get(cache, loc)
        if cached is not None:
            return cached

        resp = await self._await_busx(self.busx.list_keyword_from(locale=loc))
        rows = self._keyword_rows(resp)
        self._cache_set(cache, loc, rows)
        return rows

    async def _list_keyword_to_cached(self, s: SessionState, from_id: int) -> List[Dict[str, Any]]:
        loc = self._locale(s)
        cache = self._cache_to
        key = (loc, int(from_id))
        cached = self._cache_get(cache, key)
        if cached is not None:
            return cached

        resp = await self._await_busx(self.busx.list_keyword_to(from_keyword_id=int(from_id), locale=loc))
        rows = self._keyword_rows(resp)
        self._cache_set(cache, key, rows)
        return rows

    # -------------------------------------------------------------------------
    # Sellable-only probing helpers
    # -------------------------------------------------------------------------

    async def _discover_viable_tos_for_from(
        self,
        s: SessionState,
        from_id: int,
        *,
        max_viable: int = 10,
        probe_limit: Optional[int] = None,
        strict_destination_name: bool = False,
    ) -> Tuple[List[Dict[str, Any]], int]:
        to_rows = await self._list_keyword_to_cached(s, int(from_id))
        self._diag("discover_viable_tos:start", {"from_id": int(from_id), "strict": bool(strict_destination_name), "desired_to_text": getattr(s, "desired_to_text", None), "to_rows": len(to_rows)})

        if strict_destination_name and s.desired_to_text:
            rank_started = perf_counter()
            desired_norm = _normalize_for_match(s.desired_to_text)
            canonical_rows = self._canonical_match_rows(to_rows, s.desired_to_text, top_k=max(self.canon_strict_top_k, 12))

            # For generic place names like "Surat Thani" or "Hua Hin", the BusX API may expose
            # many rows for the same place. We only want sellable routes, so rank the most likely
            # core destination rows first (terminal/core city), keep ferries/airports later, and cap
            # the probe list so strict matching stays fast.
            same_place_rows: List[Dict[str, Any]] = []
            for r in to_rows:
                name_norm = _normalize_for_match(str(r.get("keyword_name") or ""))
                prov_norm = _normalize_for_match(str(r.get("state_province_name") or ""))
                if desired_norm and (name_norm == desired_norm or prov_norm == desired_norm):
                    same_place_rows.append(r)

            def _strict_place_rank(row: Dict[str, Any]) -> tuple:
                name = str(row.get("keyword_name") or "")
                prov = str(row.get("state_province_name") or "")
                kind = str(row.get("keyword_type") or "")
                name_norm = _normalize_for_match(name)
                prov_norm = _normalize_for_match(prov)
                text_norm = _normalize_for_match(f"{name} {prov}")

                exact_name = 1 if name_norm == desired_norm and desired_norm else 0
                exact_prov = 1 if prov_norm == desired_norm and desired_norm else 0
                # Province-level IDs (e.g. keyword_id=19 "Surat Thani") are the most
                # reliable for search_trips  -  prefer them first when name matches exactly.
                # city next, stop last (too specific, may not work with every operator).
                exact_kind_priority = {
                    "state_province": 0,
                    "city": 1,
                    "stop": 2,
                }.get(kind, 3)

                # Prefer obvious core terminal / town rows, push airport / ferry / island rows later.
                terminal_hint = 0 if any(tok in text_norm for tok in ["bus terminal", "station", "town", "center", "centre"]) else 1
                airport_penalty = 1 if "airport" in text_norm else 0
                ferry_penalty = 1 if any(tok in text_norm for tok in ["pier", "ferry", "port", "island", "koh "]) else 0
                generic_penalty = 1 if any(tok in text_norm for tok in ["intersection", "market", "school", "hospital", "university", "college", "office", "agency", "mrt", "bts", "garage", "rest stop", "bus stop"]) else 0

                # Strongly prefer rows whose own name is the requested place, then rows within the same province.
                return (
                    -exact_name,
                    -exact_prov,
                    terminal_hint,
                    airport_penalty,
                    ferry_penalty,
                    generic_penalty,
                    exact_kind_priority,
                    len(name_norm or text_norm),
                    int(row.get("keyword_id") or 0),
                )

            ranked_same_place = sorted(same_place_rows, key=_strict_place_rank)

            merged: List[Dict[str, Any]] = []
            seen_ids: set[int] = set()
            for r in ranked_same_place + canonical_rows:
                try:
                    kid = int(r.get("keyword_id"))
                except Exception:
                    continue
                if kid in seen_ids:
                    continue
                seen_ids.add(kid)
                merged.append(r)

            strict_cap = max(6, min(12, int(self.route_probe_limit or 10) + 2))
            to_rows = (merged or canonical_rows)[:strict_cap]
            rank_elapsed_ms = round((perf_counter() - rank_started) * 1000.0, 1)
            self._diag("discover_viable_tos:strict_rank", {
                "from_id": int(from_id),
                "desired_to_text": getattr(s, "desired_to_text", None),
                "same_place_count": len(same_place_rows),
                "canonical_count": len(canonical_rows),
                "merged_count": len(merged),
                "strict_cap": int(strict_cap),
                "selected_count": len(to_rows),
                "elapsed_ms": rank_elapsed_ms,
                "selected_preview": [
                    {
                        "id": int(r.get("keyword_id")),
                        "type": str(r.get("keyword_type") or ""),
                        "name": str(r.get("keyword_name") or ""),
                        "province": str(r.get("state_province_name") or ""),
                    }
                    for r in to_rows[:10]
                    if r.get("keyword_id") is not None
                ],
            })
            self._diag("discover_viable_tos:strict_matches", {"from_id": int(from_id), "match_ids": [int(r.get("keyword_id")) for r in to_rows if r.get("keyword_id") is not None], "match_labels": [str(r.get("keyword_name") or r.get("state_province_name") or "") for r in to_rows]})

        viable: List[Dict[str, Any]] = []
        tried = 0

        if strict_destination_name and s.desired_to_text:
            limit = len(to_rows) if to_rows else 0
        else:
            limit = int(probe_limit if probe_limit is not None else (self.route_probe_limit or 10))

        limit = max(1, limit) if to_rows else 0

        for tr in to_rows:
            if len(viable) >= max_viable or (limit and tried >= limit):
                break
            tried += 1
            try:
                to_id = int(tr.get("keyword_id"))
            except Exception:
                continue
            self._diag("discover_viable_tos:try_pair", {"from_id": int(from_id), "to_id": int(to_id), "to_label": str(tr.get("keyword_name") or tr.get("state_province_name") or "")})
            if await self._route_has_trips(s, int(from_id), int(to_id)):
                viable.append(tr)

        # Re-rank viable results so main terminals come before obscure stops.
        # This ensures _autoselect_to_for_from picks the best TO even when the
        # probe happened to find an obscure stop before a main terminal.
        if len(viable) > 1 and s.desired_to_text:
            _dv_norm = _normalize_for_match(s.desired_to_text)
            _obscure_stop_tokens = ["university", "college", "school", "hospital", "bus stop",
                                    "intersection", "market", "office", "agency", "mrt", "bts",
                                    "garage", "rest stop"]
            _terminal_tokens = ["bus terminal", "station", "town", "center", "centre"]
            def _viable_rank(row: Dict[str, Any]) -> tuple:
                name = str(row.get("keyword_name") or "")
                text_n = _normalize_for_match(f"{name} {str(row.get('state_province_name') or '')}")
                exact = 1 if _normalize_for_match(name) == _dv_norm and _dv_norm else 0
                term = 0 if any(t in text_n for t in _terminal_tokens) else 1
                obs = 1 if any(t in text_n for t in _obscure_stop_tokens) else 0
                air = 1 if "airport" in text_n else 0
                return (-exact, term, obs, air, int(row.get("keyword_id") or 0))
            viable.sort(key=_viable_rank)
        self._diag("discover_viable_tos:done", {"from_id": int(from_id), "tried": tried, "viable_ids": [int(r.get("keyword_id")) for r in viable if r.get("keyword_id") is not None], "viable_labels": [str(r.get("keyword_name") or r.get("state_province_name") or "") for r in viable]})
        return viable, tried

    async def _sellable_from_filter(
        self,
        s: SessionState,
        from_candidates: List[Dict[str, Any]],
        *,
        strict_destination_name: bool,
        global_pair_budget: Optional[int] = None,
        terminal_picker: bool = False,
    ) -> Dict[int, List[Dict[str, Any]]]:
        if global_pair_budget is None:
            global_pair_budget = self.strict_probe_budget if strict_destination_name else max(
                30, int(self.route_probe_limit or 10) * 3
            )

        # Terminal picker needs real trips to confirm a route exists.  Probe with
        # extra dates so a single-date "no availability" doesn't discard valid routes,
        # and so that "success:True / no trips" across ALL dates is treated as
        # "route doesn't exist" rather than "route valid, nothing available".
        extra_days = 3 if terminal_picker else 0

        budget = max(1, int(global_pair_budget))
        to_map: Dict[int, List[Dict[str, Any]]] = {}

        # Fast-path: when the destination keyword ID is already known, probe directly.
        # This bypasses list_keyword_to (which returns terminal-level IDs that may not
        # match what search_trips expects) and uses the province-level ID we resolved.
        if s.to_keyword_id:
            known_to_id = int(s.to_keyword_id)
            known_to_row = {"keyword_id": known_to_id, "keyword_name": s.to_label or str(known_to_id)}
            self._diag("sellable_from_filter:direct_probe", {"known_to_id": known_to_id, "candidates": len(from_candidates), "terminal_picker": terminal_picker, "extra_days": extra_days})
            for fr in from_candidates:
                if budget <= 0:
                    break
                try:
                    from_id = int(fr.get("keyword_id"))
                except Exception:
                    continue
                budget -= 1
                if await self._route_has_trips(s, from_id, known_to_id, extra_probe_days=extra_days):
                    to_map[from_id] = [known_to_row]
            self._diag("sellable_from_filter:direct_probe_done", {"viable_from_ids": list(to_map.keys())})
            if to_map:
                return to_map
            # Direct probe found nothing  -  the resolved TO ID is not valid for any of these FROM
            # points (e.g. wrong level/type of keyword).  Fall back to the per-FROM
            # list_keyword_to approach which finds the correct TO ID for each origin.
            self._diag("sellable_from_filter:direct_probe_fallback", {"resolved_to_id": known_to_id})
            budget = max(1, int(global_pair_budget))  # reset budget for fallback pass
            # Clear resolved TO so the fallback can discover the correct per-route TO ID.
            # Save originals so we can restore them if the fallback also finds nothing —
            # otherwise the caller loses destination context (e.g. to_keyword_id=None
            # confuses the main routing loop on the next user turn).
            _fallback_saved_to_id = known_to_id
            _fallback_saved_to_label = s.to_label
            s.to_keyword_id = None
            s.to_label = None
        else:
            _fallback_saved_to_id = None
            _fallback_saved_to_label = None

        for fr in from_candidates:
            if budget <= 0:
                break
            try:
                from_id = int(fr.get("keyword_id"))
            except Exception:
                continue

            per_from_limit = max(3, min(int(self.route_probe_limit or 10), budget))
            found, tried = await self._discover_viable_tos_for_from(
                s,
                from_id,
                max_viable=10,
                probe_limit=per_from_limit,
                strict_destination_name=strict_destination_name,
            )
            budget -= max(1, int(tried))
            if found:
                to_map[from_id] = found

        # If the fallback also found nothing, restore the original TO keyword so that
        # downstream error messages can reference the destination and the next-turn
        # routing doesn't incorrectly treat the destination as unknown.
        if not to_map and _fallback_saved_to_id is not None:
            s.to_keyword_id = _fallback_saved_to_id
            s.to_label = _fallback_saved_to_label

        return to_map

    # -------------------------------------------------------------------------
    # Picker helpers (clean UI)
    # -------------------------------------------------------------------------

    def _build_choice_options(self, matches: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        opts: List[Dict[str, Any]] = []
        for i, r in enumerate(matches, start=1):
            name = (
                str(r.get("keyword_name") or "").strip()
                or str(r.get("state_province_name") or "").strip()
                or str(r.get("keyword_id") or "")
            )
            prov = str(r.get("state_province_name") or "").strip()
            title, desc = _friendly_place_label(name, prov)
            opt: Dict[str, Any] = {"id": str(i), "label": title}
            if desc:
                opt["description"] = desc
            opts.append(opt)
        return opts

    def _invalid_choice_reply(self, s: SessionState) -> ChatResponse:
        # Don't reprint long option lists; choose_one is visible in UI.
        return self._say(s, "Please choose one of the options above.")

    def _resolve_choice_index(self, user_text: str, options: List[Dict[str, Any]]) -> Optional[int]:
        idx = parse_choice_index(user_text)
        if idx is not None:
            return idx

        q = _normalize_for_match(user_text)
        if not q or not options or len(q) < 3:
            return None

        labels = [(i, _normalize_for_match(str(opt.get("label") or ""))) for i, opt in enumerate(options, start=1)]
        hits = [i for i, lab in labels if q in lab]
        if len(hits) == 1:
            return hits[0]

        cand = get_close_matches(q, [lab for _, lab in labels], n=1, cutoff=0.86)
        if not cand:
            return None
        best = cand[0]
        for i, lab in labels:
            if lab == best:
                return i
        return None

    async def _render_from_choices(self, s: SessionState, matches: List[Dict[str, Any]], *, intro: str) -> ChatResponse:
        s.pending_from_candidates = matches
        s.awaiting_choice = "from"
        opts = self._build_choice_options(matches)
        # Diagnostic snapshot of the exact departure options shown to the user.
        self._diag("render_from_choices", {
            "intro": intro,
            "options": [
                {
                    "choice_id": str(opt.get("id")),
                    "label": str(opt.get("label")),
                    "keyword_id": int(matches[i].get("keyword_id")),
                    "keyword_name": str(matches[i].get("keyword_name") or matches[i].get("state_province_name") or ""),
                }
                for i, opt in enumerate(opts)
                if i < len(matches) and matches[i].get("keyword_id") is not None
            ],
        })
        actions = _say_with_choices(intro=intro, title="Choose a departure point", options=opts)
        return ChatResponse(actions=actions, state=s.__dict__)

    async def _render_to_choices(self, s: SessionState, matches: List[Dict[str, Any]]) -> ChatResponse:
        s.pending_to_candidates = matches
        s.awaiting_choice = "to"
        opts = self._build_choice_options(matches)
        actions = _say_with_choices(intro="Where are you going?", title="Choose a destination", options=opts)
        return ChatResponse(actions=actions, state=s.__dict__)

    # -------------------------------------------------------------------------
    # STRICT: auto lock TO after FROM pick in TO-first flow
    # -------------------------------------------------------------------------

    def _autoselect_to_for_from(self, s: SessionState, from_id: int) -> bool:
        if not s.desired_to_text:
            return False
        if s.to_keyword_id:
            return True

        tos = (s.pending_to_map_by_from_id or {}).get(int(from_id)) or []
        if not tos:
            return False

        row = tos[0]
        try:
            s.to_keyword_id = int(row.get("keyword_id"))
        except Exception:
            return False
        raw_label = str(row.get("keyword_name") or row.get("state_province_name") or s.to_keyword_id).strip()
        # If the API returns an obscure stop name (university, school, etc.) and we already
        # know the destination the user asked for, show that clean name instead.
        _obscure_display_tokens = {"university", "college", "school", "hospital", "bus stop",
                                   "intersection", "market", "office", "agency", "garage"}
        _label_lc = raw_label.lower()
        if s.desired_to_text and any(tok in _label_lc for tok in _obscure_display_tokens):
            s.to_label = str(s.desired_to_text).strip().title()
        else:
            s.to_label = raw_label
        return True

    # -------------------------------------------------------------------------
    # Keyword selection flows (sellable-only)
    # -------------------------------------------------------------------------

    async def _ensure_from_selected(self, s: SessionState, user_text: str, *, _terminal_picker: bool = False) -> ChatResponse:
        self._diag("ensure_from_selected:start", {"user_text": user_text, "state": self._diag_state(s)})

        # ── City picker re-entry (step 1 of departure selection) ──────────────
        # User picked a departure city from the interactive list.  Extract the
        # city name, set desired_from_text, then fall into the terminal picker.
        if s.awaiting_choice == "from_city" and s.pending_from_candidates:
            opts = self._build_choice_options(s.pending_from_candidates)
            idx = self._resolve_choice_index(user_text, opts)
            if idx is None or not (1 <= idx <= len(s.pending_from_candidates)):
                return self._invalid_choice_reply(s)
            row = s.pending_from_candidates[idx - 1]
            city_name = str(row.get("keyword_name") or row.get("state_province_name") or "").strip()
            self._diag("ensure_from_selected:city_choice", {"user_text": user_text, "city": city_name})
            s.desired_from_text = city_name
            s.from_query = city_name
            s.pending_from_candidates = []
            s.awaiting_choice = None
            return await self._ensure_from_selected(s, city_name, _terminal_picker=True)

        # ── Terminal picker re-entry (step 2, or direct terminal selection) ───
        if s.awaiting_choice == "from" and s.pending_from_candidates:
            opts = self._build_choice_options(s.pending_from_candidates)
            idx = self._resolve_choice_index(user_text, opts)
            if idx is None or not (1 <= idx <= len(s.pending_from_candidates)):
                return self._invalid_choice_reply(s)

            row = s.pending_from_candidates[idx - 1]
            from_id = int(row.get("keyword_id"))
            self._diag("ensure_from_selected:choice", {"user_text": user_text, "resolved_index": idx, "from_id": from_id, "from_label": str(row.get("keyword_name") or row.get("state_province_name") or "")})
            s.from_keyword_id = from_id
            s.from_label = str(row.get("keyword_name") or row.get("state_province_name") or s.from_keyword_id)

            # Save other viable FROM options before clearing, so "no trips found"
            # can suggest alternatives the user hasn't tried yet.
            _alt_map = s.pending_to_map_by_from_id or {}
            _alt_ids = set(_alt_map.keys()) - {from_id}
            _alts: List[Dict[str, Any]] = []
            for _cand in (s.pending_from_candidates or []):
                try:
                    _cid = int(_cand.get("keyword_id"))
                except Exception:
                    continue
                if _cid != from_id and _cid in _alt_ids:
                    _alts.append(_cand)
            s.viable_from_alternatives = _alts

            s.from_query = None
            s.pending_from_candidates = []
            s.awaiting_choice = None

            if self._autoselect_to_for_from(s, from_id):
                s.pending_to_map_by_from_id = {}
                return await self._advance_after_route_set(s)

            if s.desired_to_text:
                return self._ask(s, "from", f"That departure cannot sell to {s.desired_to_text}. Please pick another.")

            return self._say(s, f"✅ Departure set to: {s.from_label}\nWhere are you going TO?")

        from_text, to_text = extract_from_to(user_text)
        if from_text and to_text:
            s.desired_from_text = from_text
            s.desired_to_text = to_text
            s.from_query = from_text
            s.to_query = s.to_query or to_text
        else:
            if _normalize_cmd(user_text) in {"confirm", "reserve", "pay"}:
                return self._ask(s, "from", _PROMPT_FROM)

            if parse_date(user_text) or parse_pax(user_text):
                cleaned = _clean_place_phrase(user_text)
                if not cleaned:
                    return self._ask(s, "from", _PROMPT_FROM)

            s.from_query = _basic_sanitize(user_text).strip() or None
            if s.from_query and not s.desired_from_text:
                s.desired_from_text = s.from_query

        try:
            rows = await self._list_keyword_from_cached(s)
        except Exception as e:
            return self._say(s, "Sorry  -  I couldn't load departure locations right now.\n\n(debug) " + _dbg_exc(e))

        matches = self._canonical_match_rows(rows, s.from_query or "", top_k=self.canon_top_k)
        self._diag("ensure_from_selected:canonical_matches", {"from_query": s.from_query or "", "match_ids": [int(r.get("keyword_id")) for r in matches[:10] if r.get("keyword_id") is not None], "match_labels": [str(r.get("keyword_name") or r.get("state_province_name") or "") for r in matches[:10]]})
        if not matches:
            return self._ask(s, "from", "I couldn't find that departure. Try a nearby city/terminal name.")

        # Filter out non-transit locations (hospitals, universities, etc.) that pollute FROM matches.
        _NON_TRANSIT_TOKENS = {"university", "hospital", "school", "college", "supermarket", "mall", "hotel", "resort", "clinic", "temple", "museum"}
        transit_matches = [
            r for r in matches
            if not any(tok in _normalize_for_match(str(r.get("keyword_name") or "")) for tok in _NON_TRANSIT_TOKENS)
        ]
        if transit_matches:
            matches = transit_matches
        self._diag("ensure_from_selected:transit_filtered", {"count": len(matches), "match_ids": [int(r.get("keyword_id")) for r in matches if r.get("keyword_id") is not None]})

        # Terminal picker mode: keep only stop/station-type rows from the canonical
        # matches.  The canonical match + transit filter already found the right
        # intercity terminals (e.g. Sai Tai Mai 1223, Ekkamai 1230, Mo Chit 1216).
        # We just strip city/province-level rows — no wholesale scan of all rows.
        if _terminal_picker and self.default_from_keyword_id:
            terminal_matches = [
                r for r in matches
                if str(r.get("keyword_type") or "").strip().lower() in {"stop", "station"}
            ]
            self._diag("ensure_from_selected:terminal_picker_filtered", {"before": len(matches), "after": len(terminal_matches), "ids": [int(r.get("keyword_id")) for r in terminal_matches if r.get("keyword_id") is not None], "names": [str(r.get("keyword_name") or "") for r in terminal_matches]})
            if not terminal_matches:
                # No terminal rows in canonical match — proceed directly
                s.from_label = s.desired_from_text or self.default_from_keyword_name
                self._diag("ensure_from_selected:terminal_picker_fallback", {"reason": "no stop/station in canonical matches"})
                return await self._run_trip_search_or_recover(s)
            matches = terminal_matches

        # strict=True triggers the sellable filter.  Use desired_to_text OR to_label
        # (the latter is set when user picked a destination from the list but
        # desired_to_text was not populated yet).
        strict = bool(s.desired_to_text or s.to_label) and bool(self.strict_sellable_only)

        # Pre-resolve destination keyword ID from the FROM keyword list (province/city level IDs
        # like to_id=19 for Surat Thani work in search_trips but may not appear in list_keyword_to
        # terminal-level results).  The FROM list is already cached, so this is essentially free.
        if strict and s.desired_to_text and not s.to_keyword_id:
            try:
                _to_kw_matches = self._canonical_match_rows(rows, s.desired_to_text, top_k=5)
                for _tm in _to_kw_matches:
                    _tn = _normalize_for_match(str(_tm.get("keyword_name") or ""))
                    if any(tok in _tn for tok in _NON_TRANSIT_TOKENS):
                        continue
                    try:
                        s.to_keyword_id = int(_tm.get("keyword_id"))
                        s.to_label = str(_tm.get("keyword_name") or _tm.get("state_province_name") or s.to_keyword_id).strip()
                    except Exception:
                        pass
                    break
            except Exception:
                pass
            self._diag("ensure_from_selected:resolved_to_kw", {"desired_to_text": s.desired_to_text, "to_keyword_id": s.to_keyword_id, "to_label": s.to_label})

        if strict:
            try:
                to_map = await self._sellable_from_filter(
                    s,
                    matches,
                    strict_destination_name=True,
                    global_pair_budget=self.strict_probe_budget,
                    terminal_picker=_terminal_picker,
                )
            except Exception:
                return self._say(
                    s,
                    "I couldn't confirm sellable departures right now (API issue/timeout). "
                    "Please try again, or type reset.",
                )

            s.pending_to_map_by_from_id = to_map or {}
            self._diag("ensure_from_selected:sellable_map", {"desired_to_text": s.desired_to_text, "map": {int(k): [int(r.get("keyword_id")) for r in v if r.get("keyword_id") is not None] for k, v in (s.pending_to_map_by_from_id or {}).items()}})

            filtered: List[Dict[str, Any]] = []
            for fr in matches:
                try:
                    fid = int(fr.get("keyword_id"))
                except Exception:
                    continue
                if fid in s.pending_to_map_by_from_id and s.pending_to_map_by_from_id[fid]:
                    filtered.append(fr)

            _dest_display = s.desired_to_text or s.to_label or "your destination"
            if not filtered:
                # Clear the failed departure query so the next turn shows a fresh
                # departure prompt rather than retrying the same failed city.
                s.desired_from_text = None
                s.from_query = None
                return self._ask(
                    s,
                    "from",
                    f"No direct route to {_dest_display} from that city. "
                    "Try a different departure city, or type reset.",
                )
            matches = filtered

        self._diag("ensure_from_selected:filtered_matches", {"match_ids": [int(r.get("keyword_id")) for r in matches if r.get("keyword_id") is not None], "match_labels": [str(r.get("keyword_name") or r.get("state_province_name") or "") for r in matches]})

        # In terminal picker mode always show the list — even a single result must be
        # confirmed by the user so they know which terminal their trip departs from.
        if len(matches) == 1 and not _terminal_picker:
            row = matches[0]
            from_id = int(row.get("keyword_id"))
            s.from_keyword_id = from_id
            s.from_label = str(row.get("keyword_name") or row.get("state_province_name") or s.from_keyword_id)
            s.from_query = None

            if self._autoselect_to_for_from(s, from_id):
                s.pending_to_map_by_from_id = {}
                return await self._advance_after_route_set(s)

            _dest_display = s.desired_to_text or s.to_label
            if _dest_display:
                return self._ask(s, "from", f"That departure cannot sell to {_dest_display}. Try another name.")

            return self._say(s, f"✅ Departure set to: {s.from_label}\nWhere are you going TO?")

        _dest_display = s.desired_to_text or s.to_label
        intro = f"Trips to {_dest_display} are available from:" if _dest_display else "Where would you like to depart from?"
        return await self._render_from_choices(s, matches, intro=intro)

    async def _ensure_to_selected(self, s: SessionState, user_text: str) -> ChatResponse:
        self._diag("ensure_to_selected:start", {"user_text": user_text, "state": self._diag_state(s)})
        if not s.from_keyword_id:
            if _normalize_cmd(user_text) in {"confirm", "reserve", "pay"}:
                return self._ask(s, "to", _PROMPT_TO)

            if parse_date(user_text) or parse_pax(user_text):
                cleaned = _clean_place_phrase(user_text)
                if not cleaned:
                    return self._ask(s, "to", _PROMPT_TO)

            s.to_query = _basic_sanitize(user_text).strip() or None
            if s.to_query:
                s.desired_to_text = s.to_query

            if not s.desired_to_text:
                return self._ask(s, "to", _PROMPT_TO)

            return self._ask(
                s,
                "from",
                f"Where are you departing FROM? (I'll only show available departures for routes to {s.desired_to_text})",
            )

        if s.awaiting_choice == "to" and s.pending_to_candidates:
            opts = self._build_choice_options(s.pending_to_candidates)
            idx = self._resolve_choice_index(user_text, opts)
            if idx is None or not (1 <= idx <= len(s.pending_to_candidates)):
                return self._invalid_choice_reply(s)

            row = s.pending_to_candidates[idx - 1]
            self._diag("ensure_to_selected:choice", {"user_text": user_text, "resolved_index": idx, "to_id": int(row.get("keyword_id")), "to_label": str(row.get("keyword_name") or row.get("state_province_name") or "")})
            s.to_keyword_id = int(row.get("keyword_id"))
            s.to_label = str(row.get("keyword_name") or row.get("state_province_name") or s.to_keyword_id)
            # Populate desired_to_text so the downstream strict sellable filter
            # can run even when the user picked from a list (not typed the name).
            if not s.desired_to_text:
                _name = str(row.get("keyword_name") or "").strip()
                _prov = str(row.get("state_province_name") or "").strip()
                s.desired_to_text = _friendly_place_label(_name, _prov)[0] or s.to_label

            s.to_query = None
            s.pending_to_candidates = []
            s.awaiting_choice = None

            if s.step == "NEW":
                return await self._advance_after_route_set(s)
            return self._say(s, f"✅ Destination set to: {s.to_label}")

        if _normalize_cmd(user_text) in {"confirm", "reserve", "pay"}:
            return self._ask(s, "to", _PROMPT_TO)

        if parse_date(user_text) or parse_pax(user_text):
            cleaned = _clean_place_phrase(user_text)
            if not cleaned:
                return self._ask(s, "to", _PROMPT_TO)

        s.to_query = _basic_sanitize(user_text).strip() or None
        if s.to_query and not s.desired_to_text:
            s.desired_to_text = s.to_query

        strict = bool(s.desired_to_text)
        try:
            viable, _ = await self._discover_viable_tos_for_from(
                s,
                int(s.from_keyword_id),
                max_viable=10,
                probe_limit=max(5, int(self.route_probe_limit or 10)),
                strict_destination_name=strict,
            )
        except Exception as e:
            return self._say(s, "Sorry  -  I couldn't load destinations right now.\n\n(debug) " + _dbg_exc(e))

        self._diag("ensure_to_selected:viable_matches", {"desired_to_text": s.desired_to_text, "from_keyword_id": s.from_keyword_id, "viable_ids": [int(r.get("keyword_id")) for r in viable if r.get("keyword_id") is not None], "viable_labels": [str(r.get("keyword_name") or r.get("state_province_name") or "") for r in viable]})
        if not viable and strict:
            return self._ask(
                s,
                "to",
                f"I couldn't find a sellable destination matching '{s.desired_to_text}'. "
                "Try a different destination phrase, or type reset.",
            )

        if not viable:
            return self._ask(s, "to", "I couldn't find sellable destinations. Try another destination or type reset.")

        # If user explicitly named a destination (strict=True), auto-select the
        # best-ranked viable match rather than showing a picker.  The viable list
        # is already sorted by relevance, so viable[0] is always the best choice.
        # When strict=False (user typed nothing / browsing), show the full list.
        if strict and viable:
            row = viable[0]
            s.to_keyword_id = int(row.get("keyword_id"))
            s.to_label = str(row.get("keyword_name") or row.get("state_province_name") or s.to_keyword_id)
            s.to_query = None
            if s.step == "NEW":
                return await self._advance_after_route_set(s)
            return self._say(s, f"✅ Destination set to: {s.to_label}")

        return await self._render_to_choices(s, viable)

    # -------------------------------------------------------------------------
    # Trip search
    # -------------------------------------------------------------------------

    async def _search_trips(self, s: SessionState) -> Any:
        payload = {
            "journey_type": "OW",
            "departure_date": s.departure_date,
            "from_keyword_id": int(s.from_keyword_id or self.default_from_keyword_id),
            "to_keyword_id": int(s.to_keyword_id or self.default_to_keyword_id),
            "currency": self._currency(s),
            "locale": self._locale(s),
        }
        self._diag("final_search_trips:payload", payload)
        return await self._await_busx(
            self.busx.search_trips(
                journey_type=payload["journey_type"],
                departure_date=payload["departure_date"],
                from_keyword_id=payload["from_keyword_id"],
                to_keyword_id=payload["to_keyword_id"],
                currency=payload["currency"],
                locale=payload["locale"],
            )
        )

    async def _run_trip_search_or_recover(self, s: SessionState) -> ChatResponse:
        try:
            resp = await self._search_trips(s)
        except Exception as e:
            route = f"{s.from_label or s.from_keyword_id} → {s.to_label or s.to_keyword_id}"
            msg = (
                "Sorry  -  I couldn't complete trip search right now.\n"
                f"({route} on {s.departure_date})\n"
                "Please try again, or type 'reset'."
            )
            return self._say(s, msg + "\n\n(debug) " + _dbg_exc(e))

        trips = extract_trips(resp)
        self._diag("trip_search:extract_result", {
            "trip_count": len(trips),
            "response_summary": _summarize_probe_response(resp),
        })
        if not trips:
            s.trips = []
            s.step = "NEW"
            route = f"{s.from_label or 'your departure'} → {s.to_label or 'your destination'}"
            msg = f"😕 No trips found for **{route}** on **{s.departure_date}**."
            alts = s.viable_from_alternatives or []
            if alts:
                alt_labels = []
                for _a in alts[:3]:
                    _lbl = str(_a.get("keyword_name") or _a.get("state_province_name") or "").strip()
                    if _lbl:
                        alt_labels.append(f"**{_lbl}**")
                if alt_labels:
                    msg += (
                        f"\n\nYou might find buses departing from: {', '.join(alt_labels)}."
                        "\n\nType **reset** to start over and choose a different departure terminal."
                    )
                else:
                    msg += "\n\nType **reset** to try a different date or departure."
            else:
                msg += "\n\nTry a different date, or type **reset** to start over."
            return self._say(s, msg)

        s.trips = trips[:10]
        s.step = "PICK_TRIP"

        currency_ = self._currency(s)
        options = [format_trip_option(trip, i + 1, int(s.pax or 1), currency_) for i, trip in enumerate(s.trips)]
        _dest = s.to_label or "your destination"
        _from = s.from_label or "your departure"
        _date_str = s.departure_date or ""
        try:
            from datetime import date as _date_cls
            _d = _date_cls.fromisoformat(_date_str)
            _date_str = _d.strftime("%B ") + str(_d.day)  # e.g. "March 10"
        except Exception:
            pass
        _pax = int(s.pax or 1)
        _pax_str = f"{_pax} passenger" if _pax == 1 else f"{_pax} passengers"
        _trip_word = "option" if len(s.trips) == 1 else "options"
        intro = (
            f"Here are your {len(s.trips)} {_trip_word} for your trip to {_dest} on {_date_str} "
            f"({_pax_str}, departing from {_from})."
        )
        actions = _say_with_choices(
            intro=intro,
            title="Choose a departure time",
            options=options,
        )
        return ChatResponse(actions=actions, state=s.__dict__)

    async def _advance_after_route_set(self, s: SessionState) -> ChatResponse:
        if s.step != "NEW":
            if s.step == "PICK_TRIP" and s.trips:
                return self._say(s, "Please pick a trip number (1-10).")
            return self._say(s, "Continue where you left off, or type 'show'.")

        if not s.departure_date:
            return self._ask(s, "departure_date", _PROMPT_DATE)

        # Departure not yet confirmed — user must choose city then terminal.
        if not s.from_label and s.to_keyword_id:
            dest = s.desired_to_text or s.to_label or "your destination"
            if not s.desired_from_text:
                # Show an interactive city picker.  Load city-level rows from the
                # keyword list (state_province / city types) and present them as a
                # WhatsApp list so the user taps their departure city.
                try:
                    rows = await self._list_keyword_from_cached(s)
                except Exception as e:
                    return self._say(s, "Sorry, couldn't load departure cities right now.\n\n" + _dbg_exc(e))

                # Keep only city/province-level rows; de-dup by normalised name.
                seen_names: set = set()
                city_rows: List[Dict[str, Any]] = []
                for r in rows:
                    ktype = str(r.get("keyword_type") or "").strip().lower()
                    if ktype not in {"state_province", "city"}:
                        continue
                    nname = _normalize_for_match(str(r.get("keyword_name") or r.get("state_province_name") or ""))
                    if not nname or nname in seen_names:
                        continue
                    # Only include cities that have a _PLACE_DISPLAY entry so labels are clean.
                    if not any(key in nname for key in _PLACE_DISPLAY):
                        continue
                    seen_names.add(nname)
                    city_rows.append(r)
                    if len(city_rows) >= 10:
                        break

                if not city_rows:
                    # Fallback: plain text ask when no city rows found
                    return self._ask(s, "from", f"Which city are you departing from?")

                s.pending_from_candidates = city_rows
                s.awaiting_choice = "from_city"
                opts = self._build_choice_options(city_rows)
                actions = _say_with_choices(
                    intro=f"Which city are you departing from? Only terminals that can reach {dest} will be shown next.",
                    title="Choose departure city",
                    options=opts,
                )
                return ChatResponse(actions=actions, state=s.__dict__)

            # City known — run terminal picker filtered by destination.
            city = s.desired_from_text
            if not s.from_query:
                s.from_query = city
            return await self._ensure_from_selected(s, city, _terminal_picker=True)

        # Pax is NOT asked here  -  we search first so we only ask for ticket
        # count once we know trips actually exist on this date. Pax defaults to
        # 1 for trip display and is confirmed when the user picks a trip.
        return await self._run_trip_search_or_recover(s)

    # -------------------------------------------------------------------------
    # Booking flow helpers (1037 fix retained)
    # -------------------------------------------------------------------------

    async def _ensure_checkout_departure_ref_id(self, s: SessionState) -> None:
        if s.departure_ref_id:
            return
        if not s.selected_fare_ref_id:
            return
        if not s.pax:
            return

        try:
            resp = await self._await_busx(
                self.busx.create_checkouts(
                    fare_ref_id=s.selected_fare_ref_id,
                    adult_count=int(s.pax),
                    locale=self._locale(s),
                    currency=self._currency(s),
                )
            )
            s.checkout_response = resp
            depref = _extract_departure_ref_id_any(resp)
            if depref:
                s.departure_ref_id = depref
        except Exception:
            return

    async def _do_mark_seats(self, s: SessionState) -> Tuple[bool, str]:
        if not s.selected_fare_ref_id:
            return False, "Missing fare_ref_id. Please pick a trip again."
        if not s.selected_seats:
            return False, "No seats selected yet."

        # If the user is re-picking seats, release any existing holds first.
        try:
            if s.selected_fare_ref_id and s.seat_event_ids:
                await self._await_busx(
                    self.busx.unmark_seats(
                        fare_ref_id=str(s.selected_fare_ref_id),
                        seat_event_ids=[str(x) for x in (s.seat_event_ids or [])],
                    )
                )
                s.seat_event_ids = []
                s.mark_seats_results = None
        except Exception:
            # Non-fatal; continue attempting to hold new seats.
            pass

        passenger_type_code = s.passenger_type_code or "ADT"
        gender = s.gender or "M"
        seat_floor = int(s.seat_floor or 1)

        results: List[Any] = []
        seat_event_ids: List[str] = []

        for seat_number in s.selected_seats:
            try:
                r = await self._await_busx(
                    self.busx.mark_seats(
                        fare_ref_id=s.selected_fare_ref_id,
                        passenger_type_code=passenger_type_code,
                        gender=gender,
                        seat_number=str(seat_number),
                        seat_floor=seat_floor,
                    )
                )
            except Exception as e:
                return False, f"Sorry  -  I couldn't hold seat {seat_number} right now.\n\n(debug) " + _dbg_exc(e)

            results.append(r)
            try:
                data = r.get("data") if isinstance(r, dict) else None
                if isinstance(data, dict):
                    ev = data.get("seat_event_id") or data.get("seat_eventid")
                    if ev is not None:
                        seat_event_ids.append(str(ev))
            except Exception:
                pass

        s.mark_seats_results = results
        s.seat_event_ids = seat_event_ids
        s.step = "MARKED"

        return True, f"✅ Seats held: {', '.join(s.selected_seats)}"

    async def _do_create_reservation(self, s: SessionState) -> Tuple[bool, str]:
        if not s.seat_event_ids:
            return False, "No held seats found. Please select seats again."
        if not s.selected_fare_ref_id:
            return False, "Missing fare_ref_id. Please pick a trip again."

        currency_ = self._currency(s)
        locale_ = self._locale(s)
        time_zone_ = s.time_zone or "Asia/Bangkok"

        contact_name = s.contact_name or f"{s.passenger_name} {s.passenger_last_name}".strip()
        contact_email = s.contact_email or s.passenger_email
        contact_phone_country = s.contact_phone_country_code or s.passenger_phone_country or "TH"
        contact_phone_number = s.contact_phone_number or s.passenger_phone_number

        pax = int(s.pax or len(s.seat_event_ids) or 1)

        reservations: List[Dict[str, Any]] = []
        for i, ev in enumerate(s.seat_event_ids):
            reservations.append(
                {
                    "seat_event_id": str(ev),
                    "passenger_type_code": s.passenger_type_code or "ADT",
                    "passenger_title_id": int(s.passenger_title_id),
                    "passenger_name": _unique_passenger_name(contact_name, i, pax),
                    "passenger_gender": s.gender or "M",
                    "passenger_phone_country": s.passenger_phone_country or "TH",
                    "passenger_phone_number": s.passenger_phone_number,
                    "passenger_email": s.passenger_email,
                }
            )

        await self._ensure_checkout_departure_ref_id(s)

        candidates = _candidate_departure_ref_ids(s)
        max_attempts = max(1, int(self.checkout_depref_max_attempts or 1))
        attempts = 0
        last_err: Optional[str] = None

        async def try_wrapper_call() -> Any:
            return await self.busx.create_reservations(
                fare_ref_id=s.selected_fare_ref_id,
                reservations=reservations,
                contact_title_id=int(s.contact_title_id),
                contact_name=contact_name,
                contact_email=contact_email,
                contact_phone_country=contact_phone_country,
                contact_phone_number=contact_phone_number,
                departure_ref_id=s.departure_ref_id,
                locale=locale_,
                currency=currency_,
                time_zone=time_zone_,
            )

        async def try_internal_post(dep_ref: str) -> Any:
            post_fn = getattr(self.busx, "_post_json", None)
            try:
                import app.busx.endpoints as endpoints  # type: ignore
            except Exception as e:
                raise RuntimeError("app.busx.endpoints not available; cannot send departure_ref_id.") from e

            if post_fn is None:
                raise RuntimeError("BusXClient._post_json not available; cannot send departure_ref_id.")

            payload: Dict[str, Any] = {
                "contact": {
                    "contact_title_id": int(s.contact_title_id),
                    "contact_name": contact_name,
                    "contact_email": contact_email,
                    "contact_phone_country": contact_phone_country,
                    "contact_phone_number": contact_phone_number,
                },
                "departure": {
                    "fare_ref_id": s.selected_fare_ref_id,
                    "departure_ref_id": dep_ref,
                    "reservations": reservations,
                },
                "time_zone": time_zone_,
            }

            return await post_fn(
                endpoints.CREATE_RESERVATIONS,
                payload=payload,
                locale=locale_,
                currency=currency_,
                include_currency=True,
            )

        try:
            resp = await self._await_busx(try_wrapper_call())
            s.busx_reservation_response = resp
        except Exception as e:
            code = _exception_busx_code(e)
            if code not in {"1037", "1001", "1007"} and "does not checkout" not in str(e).lower():
                return False, "Sorry  -  I couldn't create the reservation right now.\n\n(debug) " + _dbg_exc(e)
            last_err = f"{type(e).__name__}: {e}"

        if isinstance(s.busx_reservation_response, dict):
            return self._finalize_reservation_success(s)

        for dep_ref in candidates[:max_attempts]:
            dep_ref_s = str(dep_ref).strip()
            if not dep_ref_s:
                continue
            attempts += 1
            try:
                resp = await self._await_busx(try_internal_post(dep_ref_s))
                s.departure_ref_id = dep_ref_s
                s.busx_reservation_response = resp
                break
            except Exception as e:
                code = _exception_busx_code(e)
                if code == "1037" or "does not checkout" in str(e).lower():
                    last_err = f"{type(e).__name__}: {e}"
                    continue
                return False, "Sorry  -  I couldn't create the reservation right now.\n\n(debug) " + _dbg_exc(e)

        if not isinstance(s.busx_reservation_response, dict):
            snap = {
                "attempts": attempts,
                "last_err": last_err or "Reservation failed.",
                "departure_ref_id": s.departure_ref_id,
                "candidate_departure_ref_ids": candidates[:25],
                "checkout_response": s.checkout_response,
            }
            return False, "Reservation failed after trying multiple departure reference candidates.\n\n(debug)\n" + _json_preview(snap)

        return self._finalize_reservation_success(s)

    def _finalize_reservation_success(self, s: SessionState) -> Tuple[bool, str]:
        resp = s.busx_reservation_response
        if not isinstance(resp, dict):
            return False, "Reservation failed: unexpected response shape (not a dict)."

        s.reservation_id = None
        s.order_ref_id = None

        data = resp.get("data")
        if isinstance(data, dict):
            s.reservation_id = data.get("booking_id") or data.get("reservation_id") or data.get("reservationId")
            order = data.get("order")
            if isinstance(order, dict):
                s.order_ref_id = order.get("order_ref_id") or order.get("orderRefId")
            if not s.order_ref_id:
                s.order_ref_id = data.get("order_ref_id") or data.get("orderRefId")

        s.step = "RESERVED"

        pay = _extract_payment_block(resp)
        _full_name = f"{s.passenger_name or ''} {s.passenger_last_name or ''}".strip()

        card_data: Dict[str, Any] = {
            "from_label":         s.from_label or "",
            "to_label":           s.to_label or "",
            "desired_from_text":  s.desired_from_text or "",
            "desired_to_text":    s.desired_to_text or "",
            # Prefer pipeline-detected language (e.g. "th") over the BCP-47
            # session locale ("en_US") so _route_lines shows the right script first.
            "locale":             s.chat_language or self._locale(s),
            "departure_date":     s.departure_date or "",
            "seats":              ", ".join(s.selected_seats) if getattr(s, "selected_seats", None) else "",
            "total_price":        pay.get("total_price") or "",
            "currency":           pay.get("currency") or "THB",
            "expires_at":         pay.get("expires_at") or "",
            "reservation_id":     s.reservation_id or "",
            "order_ref_id":       s.order_ref_id or "",
            "passenger_name":     _full_name,
            "passenger_email":    (s.passenger_email or "") if (s.passenger_email or "") not in {"", "test@example.com"} else "",
            "passenger_phone_number": (s.passenger_phone_number or "") if (s.passenger_phone_number or "") not in {"", "0000000000", "000000000"} else "",
        }
        return True, format_reservation_card(card_data)

    async def _refresh_reservation_details(self, s: SessionState) -> Optional[Any]:
        if not s.reservation_id:
            return None
        resp = await _call_async_method_safe(
            self.busx,
            "get_reservation_details",
            booking_id=s.reservation_id,
            time_zone=(s.time_zone or "Asia/Bangkok"),
            locale=self._locale(s),
        )
        if resp is None:
            return None
        s.busx_reservation_response = resp
        pay = _extract_payment_block(resp)
        if pay.get("order_ref_id"):
            s.order_ref_id = pay["order_ref_id"]
        return resp

    # -------------------------------------------------------------------------
    # Main handler
    # -------------------------------------------------------------------------

    async def handle(
        self,
        user_id: str,
        text: str,
        *,
        locale: Optional[str] = None,
        time_zone: Optional[str] = None,
        currency: Optional[str] = None,
        intent_envelope: Optional[dict] = None,
        state: Optional[dict] = None,
    ) -> ChatResponse:
        async with self._lock_for(user_id):
            is_new_user = user_id not in self.sessions
            s = self._get(user_id)

            if locale:
                s.locale = locale
            if time_zone:
                s.time_zone = time_zone
            if currency:
                s.currency = currency
            # Propagate pipeline-detected language so format_reservation_card
            # can render the route in the user's locale (Thai-first for "th", etc.)
            if isinstance(state, dict):
                s.chat_language = state.get("chat_language") or None

            raw = text or ""
            t = _basic_sanitize(raw)
            cmd = _normalize_cmd(t)

            # Show welcome on first-ever contact (any message from a new user).
            if is_new_user or not s.welcomed:
                return self._welcome_response(s)

            in_picker_context = bool(
                (s.awaiting_choice in {"from", "to"} and (s.pending_from_candidates or s.pending_to_candidates))
                or (s.step == "PICK_TRIP" and bool(s.trips))
                or (s.step == "PICK_SEATS")
            )

            if cmd == "reset":
                # Best-effort: release any held seats before discarding session.
                try:
                    if s.selected_fare_ref_id and s.seat_event_ids:
                        await self._await_busx(
                            self.busx.unmark_seats(
                                fare_ref_id=str(s.selected_fare_ref_id),
                                seat_event_ids=[str(x) for x in (s.seat_event_ids or [])],
                            )
                        )
                except Exception:
                    pass
                s = SessionState()
                s.locale = "en_US"  # Explicit English so welcome buttons don't inherit prior language
                if self.default_from_keyword_id:
                    s.from_keyword_id = self.default_from_keyword_id
                self.sessions[user_id] = s
                return self._welcome_response(s)

            if cmd in {"help", "show", "status", "details", "payinfo"} or cmd.startswith(
                ("locale ", "currency ", "tz ", "timezone ")
            ):
                r = await self._handle_meta_command(s, cmd, t)
                if r is not None:
                    return r

            if s.step == "NEW" and not in_picker_context and cmd not in {
                "reset",
                "help",
                "show",
                "status",
                "details",
                "payinfo",
            }:
                self._ingest_freeform_line(s, t)

            # Trip selection
            if s.step == "PICK_TRIP" and s.trips:
                idx = parse_choice_index(t)
                if idx is None or not (1 <= idx <= len(s.trips)):
                    return self._say(s, f"Please pick a trip number 1-{len(s.trips)}.")

                trip = s.trips[idx - 1]
                s.selected_index = idx
                s.selected_trip = trip
                s.selected_trip_id = str(trip.get("trip_id") or trip.get("tripId") or "") or None

                self._reset_after_new_trip_selected(s)

                fare_ref_id = ""
                fare_type0 = (trip.get("fare_type") or [{}])[0] if isinstance(trip.get("fare_type"), list) else {}
                if isinstance(fare_type0, dict):
                    fare_ref_id = str(fare_type0.get("fare_ref_id") or "").strip()
                if not fare_ref_id:
                    try:
                        for ft0 in (trip.get("fare_type") or []):
                            if isinstance(ft0, dict) and ft0.get("fare_ref_id"):
                                fare_ref_id = str(ft0.get("fare_ref_id")).strip()
                                break
                    except Exception:
                        pass
                if not fare_ref_id:
                    return self._say(s, "Sorry  -  that trip doesn't include a fare_ref_id. Please choose another trip.")

                s.selected_fare_ref_id = fare_ref_id

                try:
                    layout = await self._await_busx(
                        self.busx.get_seat_layouts(fare_ref_id=fare_ref_id, locale=self._locale(s))
                    )
                except Exception as e:
                    return self._say(
                        s,
                        "Sorry  -  I couldn't load seat layout right now. Please choose another trip.\n\n(debug) "
                        + _dbg_exc(e),
                    )

                s.seat_layouts[fare_ref_id] = layout
                s.last_seat_layout = layout
                s.available_seats = extract_seats_from_layout(layout)
                s.step = "PICK_SEATS"

                if not s.pax:
                    s.pax = 1

                if not s.available_seats:
                    return self._say(
                        s,
                        "Seat map loaded, but no available seats were detected. You can still try typing seat numbers, or choose another trip.",
                    )

                preview = ", ".join(s.available_seats[:60])
                more = f" (+{max(0, len(s.available_seats) - 60)} more)" if len(s.available_seats) > 60 else ""
                return self._say(
                    s,
                    f"✅ Trip selected.\nAvailable seats: {preview}{more}\n\nReply with {s.pax} seat number(s) (example: 12,13).",
                )

            # Seat selection
            if s.step == "PICK_SEATS":
                seats = parse_seats(t)
                if not seats:
                    if cmd in {"reserve", "pay"}:
                        return self._say(s, "Please pick seat number(s) first (example: 12,13).")
                    return self._say(s, "Reply with seat numbers (e.g. '12 13' or '12,13').")

                if s.available_seats:
                    bad = [x for x in seats if x not in s.available_seats]
                    if bad:
                        preview = ", ".join(s.available_seats[:30])
                        return self._say(s, f"These seats aren't available: {', '.join(bad)}. Try from: {preview}")

                if not s.pax:
                    return self._say(s, "Missing ticket count. Type '2' or '2 pax'.")

                if len(seats) != int(s.pax):
                    return self._say(s, f"Need exactly {s.pax} seat(s). You sent {len(seats)}.")

                s.selected_seats = seats

                if self.auto_reserve_after_seats:
                    s.step = "READY"

                    ok1, msg1 = await self._do_mark_seats(s)
                    if not ok1:
                        s.step = "READY"
                        return self._say(s, f"Seats selected: {', '.join(seats)}.\n\nERROR: {msg1}\n\nType 'reserve' to try again.")

                    # Collect passenger/contact details before creating reservation.
                    s.last_hold_message = msg1
                    if _looks_like_default_details(s):
                        s.step = "DETAILS_NAME"
                        return self._ask(s, "passenger_name",
                            f"{msg1}\n\nGreat! I just need a few details to complete your booking.\nWhat is your first and last name?")

                    ok2, msg2 = await self._do_create_reservation(s)
                    if not ok2:
                        s.step = "MARKED"
                        return self._say(s, f"{msg1}\n\nMarked OK, but reservation failed:\n{msg2}\n\nType 'reserve' to retry.")

                    return self._say_with_booking_buttons(s, msg2)

                s.step = "READY"
                return self._say(s, f"Selected seats: {', '.join(seats)}. Next: type 'reserve'.")

            # ---------------------------------------------------------------
            # Conversational passenger details  -  one field at a time
            # ---------------------------------------------------------------
            def _norm_phone(raw: str, ctry: str) -> Tuple[Optional[str], Optional[str]]:
                p = (raw or "").strip()
                if not p:
                    return None, "Please enter your phone number."
                digits = re.sub(r"\D+", "", p)
                c = (ctry or "").strip().upper() or "TH"
                if c == "TH":
                    if digits.startswith("66") and len(digits) in {11, 12}:
                        digits = "0" + digits[2:]
                    if len(digits) != 10:
                        return None, "Thai numbers need 10 digits  -  e.g. 0812345678 or +66812345678."
                    if not digits.startswith("0"):
                        return None, "Thai numbers should start with 0  -  e.g. 0812345678."
                else:
                    if len(digits) < 6:
                        return None, "That number looks too short. Please include your country code."
                return digits, None

            def _detect_phone_country(raw: str) -> str:
                p = (raw or "").strip()
                if p.startswith("+66") or re.sub(r"\D+", "", p).startswith("66"):
                    return "TH"
                if p.startswith("+1"):
                    return "US"
                if p.startswith("+44"):
                    return "GB"
                if p.startswith("+61"):
                    return "AU"
                if p.startswith("+"):
                    return "INTL"
                return "TH"  # default to Thailand if no prefix

            if s.step == "DETAILS_NAME":
                raw_name = t.strip().strip(".,!?")
                parts = raw_name.split()
                if len(parts) < 2:
                    return self._ask(s, "passenger_name",
                        "Please enter your first and last name  -  e.g. John Smith")
                s.passenger_name = parts[0].title()
                s.passenger_last_name = " ".join(parts[1:]).title()
                s.step = "DETAILS_EMAIL"
                return self._ask(s, "passenger_email",
                    f"Nice to meet you, {s.passenger_name}! What is your email address?\n"
                    "(Your booking confirmation will be sent here)")

            if s.step == "DETAILS_EMAIL":
                email = t.strip().lower()
                if not email or "@" not in email or "." not in email.split("@")[-1]:
                    return self._ask(s, "passenger_email",
                        f"Please enter a valid email address, {s.passenger_name or 'there'}  -  e.g. name@gmail.com")
                s.passenger_email = email
                s.contact_email = email
                s.step = "DETAILS_PHONE"
                return self._ask(s, "passenger_phone",
                    f"Almost done, {s.passenger_name}! What is your phone number?\n"
                    "Please include your country code  -  e.g.\n"
                    "+66 81 234 5678 (Thailand)\n"
                    "+1 555 123 4567 (USA)")

            if s.step == "DETAILS_PHONE":
                country = _detect_phone_country(t)
                norm, err = _norm_phone(t, country)
                if err:
                    return self._ask(s, "passenger_phone",
                        f"Sorry, {s.passenger_name or 'there'}  -  {err}\n"
                        "Example: +66812345678 (Thailand) or +15551234567 (USA)")
                s.passenger_phone_number = norm
                s.contact_phone_number = norm
                s.passenger_phone_country = country if country != "INTL" else "TH"
                s.contact_phone_country_code = s.passenger_phone_country
                s.contact_name = f"{s.passenger_name} {s.passenger_last_name}".strip()
                s.details_collected = True

                ok2, msg2 = await self._do_create_reservation(s)
                if not ok2:
                    s.step = "MARKED"
                    return self._say(s, f"Thank you, {s.passenger_name}! Your seats are held.\n\nHowever, there was an issue creating the reservation:\n{msg2}\n\nType 'reserve' to try again.")

                return self._say_with_booking_buttons(s, msg2)

            # READY+ commands
            if s.step in {"READY", "MARKED", "RESERVED", "PAYMENT_PENDING", "PAID"}:
                if s.step == "READY" and cmd == "reserve":
                    ok1, msg1 = await self._do_mark_seats(s)
                    if not ok1:
                        return self._say(s, f"ERROR: {msg1}")

                    s.last_hold_message = msg1
                    if _looks_like_default_details(s):
                        s.step = "DETAILS_NAME"
                        return self._ask(s, "passenger_name",
                            f"{msg1}\n\nGreat! I just need a few details to complete your booking.\nWhat is your first and last name?")

                    ok2, msg2 = await self._do_create_reservation(s)
                    if not ok2:
                        s.step = "MARKED"
                        return self._say(s, f"Marked OK, but reservation failed:\n{msg2}\n\nType 'reserve' to retry.")

                    return self._say_with_booking_buttons(s, msg2)

                if s.step == "MARKED" and cmd == "reserve":
                    if _looks_like_default_details(s):
                        s.step = "DETAILS_NAME"
                        return self._ask(s, "passenger_name",
                            f"{(s.last_hold_message or '✅ Seats held.')}\n\nLet me get your details to complete the booking.\nWhat is your first and last name?")
                    ok2, msg2 = await self._do_create_reservation(s)
                    if not ok2:
                        return self._say(s, msg2)
                    return self._say_with_booking_buttons(s, msg2)

                if s.step in {"RESERVED", "PAYMENT_PENDING"} and cmd == "pay":
                    if not s.order_ref_id:
                        return self._say(s, "Cannot pay: order_ref_id missing. Run 'reserve' first.")

                    try:
                        pmt = await self._await_busx(
                            self.busx.create_payments(order_ref_id=s.order_ref_id, locale=self._locale(s))
                        )
                    except Exception as e:
                        return self._say(s, "create_payments failed.\n\n(debug) " + _dbg_exc(e))

                    s.busx_payment_response = pmt
                    s.step = "PAYMENT_PENDING"

                    payment_url = None
                    if isinstance(pmt, dict):
                        data = pmt.get("data")
                        if isinstance(data, dict):
                            for k in ("payment_url", "url", "redirect_url", "checkout_url"):
                                if data.get(k):
                                    payment_url = str(data.get(k))
                                    break

                    pay = _extract_payment_block(s.busx_reservation_response)
                    _DIV = "─────────────────"
                    lines = ["💳 *Payment Initiated*", "", _DIV]
                    if pay.get("total_price") and pay.get("currency"):
                        lines.append(f"💰  {_fmt_amount(pay['total_price'], pay.get('currency','THB'))}")
                    if s.reservation_id:
                        lines.append(f"🔖  *{s.reservation_id}*")
                    if s.order_ref_id:
                        lines.append(f"    _{s.order_ref_id}_")
                    if pay.get("paycode"):
                        lines.append(f"🔑  {pay['paycode']}")
                    if pay.get("expires_at"):
                        lines.append(f"⏰  Pay by:  {_fmt_expiry(pay['expires_at'])}")
                    lines.append(_DIV)
                    if payment_url:
                        lines += ["", "🌐 *Complete payment here:*", payment_url]
                    else:
                        lines += ["", "⏳ Awaiting payment confirmation."]
                    lines += ["", "Use *status* to check when payment is confirmed."]

                    return self._say(s, "\n".join(lines))

                if s.step in {"RESERVED", "PAYMENT_PENDING"} and cmd == "cancel":
                    if not s.reservation_id:
                        return self._say(s, "No active booking to cancel.")
                    s.step = "CANCEL_CONFIRM"
                    return ChatResponse(
                        actions=[
                            Action(type="say", payload={"text": f"⚠️ Cancel booking *{s.reservation_id}*?\nThis cannot be undone."}),
                            Action(type="choose_one", payload={
                                "title": "Confirm cancellation",
                                "options": [
                                    {"id": "cancel_yes", "label": "✅ Yes, cancel"},
                                    {"id": "cancel_no",  "label": "❌ Keep booking"},
                                ],
                            }),
                        ],
                        state=s.__dict__,
                    )

                if s.step == "CANCEL_CONFIRM":
                    if cmd in {"cancel_yes", "yes", "confirm"}:
                        if not s.reservation_id:
                            self._reset_session(s)
                            return self._say(s, "No active booking found.")
                        try:
                            await self._await_busx(
                                self.busx.cancel_reservations(booking_id=s.reservation_id, locale=self._locale(s))
                            )
                        except Exception as e:
                            s.step = "RESERVED"
                            return self._say(s, "Cancel failed.\n\n(debug) " + _dbg_exc(e))
                        booking_id = s.reservation_id
                        self._reset_session(s)
                        return self._say(s, f"✅ Booking {booking_id} has been cancelled.")
                    else:
                        s.step = "RESERVED"
                        return self._say(s, "OK — your booking is still active.")

                if s.step in {"RESERVED", "PAYMENT_PENDING"} and cmd == "change":
                    if not s.reservation_id:
                        return self._say(s, "No active booking to change.")
                    # Extract global ticket numbers from reservation response
                    tickets: List[str] = []
                    resp_data = s.busx_reservation_response
                    if isinstance(resp_data, dict):
                        data = resp_data.get("data") or resp_data
                        if isinstance(data, dict):
                            for ticket in (data.get("tickets") or data.get("global_tickets") or []):
                                if isinstance(ticket, dict):
                                    gtn = ticket.get("global_ticket_number")
                                    if gtn:
                                        tickets.append(str(gtn))
                    if not tickets:
                        return self._say(s, "Cannot change: ticket numbers not found in booking. Contact support.")
                    try:
                        result = await self._await_busx(
                            self.busx.request_rebookings(global_ticket_numbers=tickets, locale=self._locale(s))
                        )
                    except Exception as e:
                        return self._say(s, "Change request failed.\n\n(debug) " + _dbg_exc(e))
                    # Check if rebooking is allowed
                    allow = False
                    if isinstance(result, dict):
                        for item in (result.get("data") or []):
                            if isinstance(item, dict):
                                std = item.get("set_travel_date") or {}
                                if isinstance(std, dict) and (std.get("allow_rebooking") or "").upper() == "Y":
                                    allow = True
                                    break
                    if not allow:
                        return self._say(s, "Sorry — rebooking is not permitted for this ticket. Please contact support.")
                    # Preserve route so user only needs to pick a new date
                    saved_from_kw   = s.from_keyword_id
                    saved_to_kw     = s.to_keyword_id
                    saved_from_lbl  = s.from_label
                    saved_to_lbl    = s.to_label
                    saved_from_q    = s.from_query
                    saved_to_q      = s.to_query
                    saved_from_text = s.desired_from_text
                    saved_to_text   = s.desired_to_text
                    self._reset_session(s)
                    s.from_keyword_id   = saved_from_kw
                    s.to_keyword_id     = saved_to_kw
                    s.from_label        = saved_from_lbl
                    s.to_label          = saved_to_lbl
                    s.from_query        = saved_from_q
                    s.to_query          = saved_to_q
                    s.desired_from_text = saved_from_text
                    s.desired_to_text   = saved_to_text
                    route = f"{saved_from_lbl} → {saved_to_lbl}" if saved_from_lbl and saved_to_lbl else "your route"
                    return self._ask(s, "departure_date",
                        f"✅ Rebooking approved — previous booking released.\n\n🚌 *{route}*\n\nWhat date would you like to travel?")

                # Guardrail: after booking, users sometimes tap old UI chips (e.g. "1")
                # or the UI double-submits. Don't respond with a dead-end error.
                if s.step in {"RESERVED", "PAYMENT_PENDING", "PAID"} and parse_choice_index(t) is not None:
                    return self._say(s, "You're all booked! Use the buttons to pay, cancel, or change — or type *status* to check payment.")

                suggestion = _suggest_command(t)
                if suggestion and suggestion != cmd:
                    return self._say(s, f"I didn't understand '{t}'. Did you mean '{suggestion}'?")
                return self._say(s, "I didn't understand that. Say 'help' for options.")

            # NEW flow: only ask date if we truly have nothing usable
            if s.step == "NEW" and not s.departure_date and not s.desired_to_text and not s.to_keyword_id:
                return self._ask(s, "departure_date", _PROMPT_DATE)

            if self.soft_guidance and cmd == "pay" and s.step not in {"RESERVED", "PAYMENT_PENDING", "PAID"}:
                return self._say(s, "To pay, first choose a route + date, then pick a trip and seats.")

            if s.step == "NEW":
                if not s.desired_to_text and not s.to_keyword_id:
                    return await self._ensure_to_selected(s, t)
                if not s.from_keyword_id:
                    return await self._ensure_from_selected(s, t)
                if not s.to_keyword_id:
                    return await self._ensure_to_selected(s, t)
                # Destination known but departure city/terminal not yet confirmed —
                # process user input as a departure answer (city or terminal name).
                if s.to_keyword_id and not s.from_label:
                    return await self._ensure_from_selected(s, t, _terminal_picker=True)
                if s.departure_date and s.from_keyword_id and s.to_keyword_id:
                    return await self._advance_after_route_set(s)

            if not s.pax:
                return self._ask(s, "pax", _PROMPT_PAX)
            return await self._run_trip_search_or_recover(s)

    # -------------------------------------------------------------------------
    # Meta commands
    # -------------------------------------------------------------------------

    async def _handle_meta_command(self, s: SessionState, cmd: str, raw_text: str) -> Optional[ChatResponse]:
        if cmd == "help":
            return self._say(
                s,
                "Flow: date → destination (TO) → departure (FROM) → tickets → choose trip → seats → reserve → pay\n"
                "Commands: status, details, payinfo, show, reset.\n"
                "Tip: You can type one line like: 'Bangkok to Krabi tomorrow 1 pax'.",
            )

        if cmd.startswith("locale "):
            s.locale = _basic_sanitize(raw_text).split(None, 1)[1].strip()
            return self._say(s, f"OK. locale={s.locale}")

        if cmd.startswith("currency "):
            s.currency = _basic_sanitize(raw_text).split(None, 1)[1].strip().upper()
            return self._say(s, f"OK. currency={s.currency}")

        if cmd.startswith(("tz ", "timezone ")):
            s.time_zone = _basic_sanitize(raw_text).split(None, 1)[1].strip()
            return self._say(s, f"OK. time_zone={s.time_zone}")

        if cmd == "show":
            snap = {
                "step": s.step,
                "from_keyword_id": s.from_keyword_id,
                "to_keyword_id": s.to_keyword_id,
                "from_label": s.from_label,
                "to_label": s.to_label,
                "awaiting_choice": s.awaiting_choice,
                "departure_date": s.departure_date,
                "pax": s.pax,
                "selected_fare_ref_id": s.selected_fare_ref_id,
                "departure_ref_id": s.departure_ref_id,
                "selected_trip_id": s.selected_trip_id,
                "selected_index": s.selected_index,
                "selected_seats": s.selected_seats,
                "available_seats_sample": (s.available_seats or [])[:30],
                "seat_event_ids": s.seat_event_ids,
                "reservation_id": s.reservation_id,
                "order_ref_id": s.order_ref_id,
                "desired_from_text": s.desired_from_text,
                "desired_to_text": s.desired_to_text,
                "pending_to_map_by_from_id_keys": list((s.pending_to_map_by_from_id or {}).keys())[:20],
                "selected_trip": s.selected_trip,
                "last_seat_layout": s.last_seat_layout,
                "mark_seats_results": s.mark_seats_results,
                "checkout_response": s.checkout_response,
                "candidate_departure_ref_ids": _candidate_departure_ref_ids(s)[:25],
                "auto_reserve_after_seats": self.auto_reserve_after_seats,
                "has_internal_post_json": bool(getattr(self.busx, "_post_json", None)),
                "strict_sellable_only": self.strict_sellable_only,
                "strict_probe_budget": self.strict_probe_budget,
                "canon_min_score": self.canon_min_score,
                "canon_top_k": self.canon_top_k,
                "canon_strict_top_k": self.canon_strict_top_k,
            }
            return self._say(s, _json_preview(snap))

        if cmd in {"status", "details", "payinfo"} and not s.reservation_id:
            return self._say(s, "No active reservation yet. Start with: 'Bangkok to Krabi tomorrow 1 pax'.")

        if cmd == "status":
            try:
                resp = await self._refresh_reservation_details(s)
            except Exception as e:
                return self._say(s, "Sorry  -  status check failed.\n\n(debug) " + _dbg_exc(e))

            payload = resp or s.busx_reservation_response
            pay = _extract_payment_block(payload)

            try:
                if (pay.get("payment_status") or "").upper() == "Y":
                    s.step = "PAID"
                elif (pay.get("payment_required") or "").upper() == "Y":
                    s.step = "PAYMENT_PENDING"
            except Exception:
                pass

            lines = [
                f"reservation_id: {s.reservation_id}",
                f"order_ref_id:  {(s.order_ref_id or pay.get('order_ref_id') or '')}".rstrip(),
            ]
            if pay.get("total_price") and pay.get("currency"):
                lines.append(f"amount:      {pay['total_price']} {pay['currency']}")
            if pay.get("payment_status") is not None:
                lines.append(f"pay_status:  {pay['payment_status']}")
            if pay.get("expires_at"):
                lines.append(f"expires_at:  {pay['expires_at']}")
            if pay.get("paycode"):
                lines.append(f"paycode:     {pay['paycode']}")
            return self._say(s, "\n".join(lines))

        if cmd == "details":
            resp = None
            err = None
            try:
                resp = await self._refresh_reservation_details(s)
            except Exception as e:
                err = _dbg_exc(e)

            payload = resp or s.busx_reservation_response or s.busx_payment_response
            if payload is None:
                if err:
                    return self._say(s, f"details: no payload available.\nrefresh error: {err}")
                return self._say(s, "details: no payload available.")

            head = ""
            if err:
                head = f"(refresh failed; showing cached payload)\n{err}\n\n"
            elif resp is None:
                head = "(refresh not available; showing cached payload)\n\n"

            pay = _extract_payment_block(payload)
            pay_lines = [
                "PAYMENT BLOCK (extracted):",
                f"order_ref_id:       {pay.get('order_ref_id') or ''}".rstrip(),
                f"payment_required:   {pay.get('payment_required') or ''}".rstrip(),
                f"payment_status:     {pay.get('payment_status') or ''}".rstrip(),
                f"total_price:        {pay.get('total_price') or ''}".rstrip(),
                f"currency:           {pay.get('currency') or ''}".rstrip(),
                f"expires_at:         {pay.get('expires_at') or ''}".rstrip(),
                f"paycode:            {pay.get('paycode') or ''}".rstrip(),
                "",
            ]
            return self._say(s, head + "\n".join(pay_lines) + _json_preview(payload, max_chars=6000))

        if cmd == "payinfo":
            resp = None
            err = None
            try:
                resp = await self._refresh_reservation_details(s)
            except Exception as e:
                err = _dbg_exc(e)

            payload = resp or s.busx_reservation_response or s.busx_payment_response
            if payload is None:
                if err:
                    return self._say(s, f"payinfo: no payload available.\nrefresh error: {err}")
                return self._say(s, "payinfo: no payload available.")

            hints = _find_payment_hints(payload)

            head = ""
            if err:
                head = f"(refresh failed; scanned cached payload)\n{err}\n\n"
            elif resp is None:
                head = "(refresh not available; scanned cached payload)\n\n"

            if not hints:
                return self._say(s, head + "PAYINFO: no obvious provider URLs/QR/ref fields found in payload.")

            lines = ["PAYINFO (found keys):"]
            for k, v in hints.items():
                lines.append(f"{k}: {v}")
            return self._say(s, head + "\n".join(lines))

        return None