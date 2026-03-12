"""
app/busx/intent/claude_nlp.py
──────────────────────────────
Claude Haiku–powered intent parser.

Replaces the deterministic stub in llm_stub.py with a real LLM call.
Returns the identical dict shape so the orchestrator needs zero changes.

Why Haiku:
  • ~10–15x cheaper than Sonnet, fast enough for real-time chat
  • Still handles typos, Thai/CJK, relative dates, mixed languages

Graceful degradation:
  • If ANTHROPIC_API_KEY is missing → falls back to llm_stub silently
  • If the API call fails / times out → falls back to llm_stub silently
  • No user-visible error in either case

Called from:
  app/busx/intent_api.py  →  parse_intent()  when _use_claude() is True
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, timedelta
from typing import Any, Dict, List, Optional
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

# ─── API config ───────────────────────────────────────────────────────────────

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_MODEL         = "claude-haiku-4-5-20251001"
_TIMEOUT       = 10.0   # seconds — WhatsApp requires reply < 15 s total
_MAX_TOKENS    = 400


def _api_key() -> str:
    k = os.getenv("ANTHROPIC_API_KEY", "").strip()
    if not k:
        raise RuntimeError("ANTHROPIC_API_KEY not set")
    return k


# ─── Date helpers (Bangkok timezone) ──────────────────────────────────────────

def _today_bkk(tz: str = "Asia/Bangkok") -> date:
    try:
        from datetime import datetime
        return datetime.now(ZoneInfo(tz)).date()
    except Exception:
        return date.today()


def _date_ctx(tz: str) -> str:
    """Build date reference string injected into the system prompt."""
    t = _today_bkk(tz)
    tmr = t + timedelta(days=1)
    # next Friday / Saturday / Sunday
    fri = t + timedelta(days=(4 - t.weekday()) % 7 or 7)
    sat = t + timedelta(days=(5 - t.weekday()) % 7 or 7)
    sun = t + timedelta(days=(6 - t.weekday()) % 7 or 7)
    return (
        f"TODAY={t.isoformat()} ({t.strftime('%A')}), "
        f"TOMORROW={tmr.isoformat()}, "
        f"NEXT_FRI={fri.isoformat()}, "
        f"NEXT_SAT={sat.isoformat()}, "
        f"NEXT_SUN={sun.isoformat()}"
    )


# ─── System prompt ────────────────────────────────────────────────────────────

_SYSTEM = """You are the NLP parser for a Thai bus ticket booking chatbot.
Extract structured booking intent from the user message.
Output ONLY a single valid JSON object — no markdown fences, no explanation.

Current date reference: {DATE_CTX}

JSON schema to output:
{{
  "intent":           "TripSearch" | "Reset" | "Cancel" | "Status" | "Help" | "Unknown",
  "from_name":        string | null,
  "to_name":          string | null,
  "departure_date":   "YYYY-MM-DD" | null,
  "adult_count":      integer,
  "confidence":       float 0–1,
  "detected_language": string   (ISO 639-1: "en","th","zh","ja","ko","de","fr","ru"…)
}}

City normalisation (map everything to standard English):
  กรุงเทพ / BKK / Bankgok / Bangkik / bkk  →  "Bangkok"
  ภูเก็ต  / Phukeet / phuket               →  "Phuket"
  เชียงใหม่ / Chiang mai / chiangmai        →  "Chiang Mai"
  กระบี่   / krabi                          →  "Krabi"
  พัทยา   / pattaya                         →  "Pattaya"
  เกาะสมุย / koh samui                      →  "Koh Samui"
  หัวหิน   / hua hin                        →  "Hua Hin"
  สุราษฎร์ธานี / surat / surat thani       →  "Surat Thani"
  If unclear, return null — do NOT guess.

Date rules:
  today → TODAY, tomorrow/tmrw/พรุ่งนี้/明日 → TOMORROW
  "next Friday" → NEXT_FRI, "next Saturday" → NEXT_SAT, etc.
  Calculate all relative dates from the DATE_CTX above.
  If no date mentioned → null.

Intent rules:
  "reset" / "start over" / "restart" / "เริ่มใหม่"  →  Reset
  "cancel" / "refund"                                →  Cancel
  "status" / "check my booking"                     →  Status
  "help" / "what can you do"                        →  Help
  A bare digit like "2" with no other context       →  Unknown

Default adult_count = 1 if not stated.

Examples:
  "Bangkok to Phuket tmrw 2 ppl"
  → {{"intent":"TripSearch","from_name":"Bangkok","to_name":"Phuket","departure_date":"{TOMORROW}","adult_count":2,"confidence":0.95,"detected_language":"en"}}

  "กรุงเทพไปเชียงใหม่ พรุ่งนี้"
  → {{"intent":"TripSearch","from_name":"Bangkok","to_name":"Chiang Mai","departure_date":"{TOMORROW}","adult_count":1,"confidence":0.90,"detected_language":"th"}}

  "Bangkik to phukeet next friday 1 ticket"
  → {{"intent":"TripSearch","from_name":"Bangkok","to_name":"Phuket","departure_date":"{NEXT_FRI}","adult_count":1,"confidence":0.82,"detected_language":"en"}}

  "reset"
  → {{"intent":"Reset","from_name":null,"to_name":null,"departure_date":null,"adult_count":1,"confidence":0.99,"detected_language":"en"}}
"""


def _build_system(tz: str) -> str:
    ctx = _date_ctx(tz)
    t = _today_bkk(tz)
    tmr = (t + timedelta(days=1)).isoformat()
    fri = (t + timedelta(days=(4 - t.weekday()) % 7 or 7)).isoformat()
    return (
        _SYSTEM
        .replace("{DATE_CTX}", ctx)
        .replace("{TOMORROW}", tmr)
        .replace("{NEXT_FRI}", fri)
    )


# ─── Claude API call ──────────────────────────────────────────────────────────

async def _call_claude(
    user_msg: str,
    tz: str,
    client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    payload = {
        "model": _MODEL,
        "max_tokens": _MAX_TOKENS,
        "system": _build_system(tz),
        "messages": [{"role": "user", "content": user_msg}],
    }
    headers = {
        "Content-Type": "application/json",
        "x-api-key": _api_key(),
        "anthropic-version": "2023-06-01",
    }
    own = client is None
    c   = client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        r = await c.post(_ANTHROPIC_URL, json=payload, headers=headers, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        raw  = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        # strip accidental markdown fences
        raw  = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw  = re.sub(r"\s*```$", "", raw)
        return json.loads(raw.strip())
    finally:
        if own:
            await c.aclose()


# ─── Public entry point ───────────────────────────────────────────────────────

async def normalize_intent_claude(
    text: str,
    *,
    locale: str = "en_US",
    time_zone: str = "Asia/Bangkok",
    currency: str = "THB",
    session_state: Optional[Dict[str, Any]] = None,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """
    Parse raw user text → NormalizedIntent dict.

    Returns the exact same shape as intent_api.py's _parse_*() helpers,
    so the orchestrator consumes it with zero changes.

    Falls back to llm_stub.normalize_intent_stub() on any error.
    """
    text = (text or "").strip()
    if not text:
        return _empty(locale, time_zone, currency)

    # Add session context so Claude can resolve references like "same route"
    user_msg = text
    if session_state:
        parts: List[str] = []
        step = session_state.get("step", "")
        if session_state.get("from_label"):
            parts.append(f"from={session_state['from_label']}")
        if session_state.get("to_label"):
            parts.append(f"to={session_state['to_label']}")
        if session_state.get("departure_date"):
            parts.append(f"date={session_state['departure_date']}")
        if parts:
            user_msg = f"[context: step={step}, {', '.join(parts)}]\n{text}"

    try:
        parsed = await _call_claude(user_msg, time_zone, http_client)
    except Exception as exc:
        log.warning("Claude NLP failed (%s) – falling back to regex stub", exc)
        return _fallback(text, locale, time_zone, currency)

    intent        = parsed.get("intent", "Unknown")
    from_name     = parsed.get("from_name")
    to_name       = parsed.get("to_name")
    dep_date      = parsed.get("departure_date")
    adult_count   = int(parsed.get("adult_count") or 1)
    confidence    = float(parsed.get("confidence") or 0.5)
    detected_lang = parsed.get("detected_language", "en")

    missing: List[str] = []
    if intent == "TripSearch":
        if not from_name: missing.append("from.name")
        if not to_name:   missing.append("to.name")
        if not dep_date:  missing.append("departure_date")

    return {
        "intent":            intent,
        "confidence":        confidence,
        "original_text":     text,
        "detected_language": detected_lang,
        "locale":            locale,
        "time_zone":         time_zone,
        "currency":          currency,
        "payload": {
            "trip_search": {
                "journey_type":   "OW",
                "departure_date": dep_date,
                "from":           {"name": from_name} if from_name else {},
                "to":             {"name": to_name}   if to_name   else {},
                "passengers":     {"adult_count": adult_count},
            }
        } if intent == "TripSearch" else {},
        "missing_fields": missing,
    }


def _empty(locale: str, time_zone: str, currency: str) -> Dict[str, Any]:
    return {
        "intent": "Unknown", "confidence": 0.0, "original_text": "",
        "detected_language": "en", "locale": locale,
        "time_zone": time_zone, "currency": currency,
        "payload": {}, "missing_fields": [],
    }


def _fallback(text: str, locale: str, time_zone: str, currency: str) -> Dict[str, Any]:
    """Use the original regex stub as graceful degradation."""
    try:
        from app.busx.intent.llm_stub import normalize_intent_stub
        result = normalize_intent_stub(text, locale=locale, time_zone=time_zone, currency=currency)
        result.setdefault("missing_fields", [])
        return result
    except Exception:
        return _empty(locale, time_zone, currency)
