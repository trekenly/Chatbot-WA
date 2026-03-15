"""app/busx/claude_intent.py
──────────────────────────
Lightweight Claude Haiku call that runs on every inbound message to extract
structured booking intent AND the user's language.

Returns a plain dict:
    {
        "from_name":       str | None,
        "to_name":         str | None,
        "departure_date":  "YYYY-MM-DD" | None,
        "pax":             int,
        "intent":          "book" | "reset" | "help" | "status" | "unknown",
        "language":        str   (ISO-639-1, e.g. "en","th","ja","zh","ko","ru","ar")
    }

Graceful degradation:
  • ANTHROPIC_API_KEY missing  → returns _default() silently
  • API call fails / times out → returns _default() silently
"""
from __future__ import annotations

import json
import logging
import os
import re
from datetime import date, datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

import httpx

log = logging.getLogger(__name__)

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_MODEL         = "claude-haiku-4-5-20251001"
_TIMEOUT       = 8.0
_MAX_TOKENS    = 200


def _api_key() -> Optional[str]:
    k = os.getenv("ANTHROPIC_API_KEY", "").strip()
    return k if k else None


def _today(tz: str = "Asia/Bangkok") -> date:
    try:
        return datetime.now(ZoneInfo(tz)).date()
    except Exception:
        return date.today()


_SYSTEM = """\
Extract booking intent from a bus-ticket chatbot user message.
Output ONLY a single valid JSON object — no explanation, no markdown fences.

Today is {TODAY}. Tomorrow is {TOMORROW}.

JSON schema:
{{
  "intent":          "book" | "reset" | "help" | "status" | "unknown",
  "from_name":       string | null,
  "to_name":         string | null,
  "departure_date":  "YYYY-MM-DD" | null,
  "pax":             integer (default 1),
  "language":        string (ISO-639-1, e.g. "en","th","ja","zh","ko","ru","ar")
}}

City normalisation (always output standard English name):
  กรุงเทพ / BKK / bkk / Bangkok / 曼谷 / 방콕 / バンコク  →  "Bangkok"
  ภูเก็ต  / phuket / 普吉 / 푸켓 / プーケット            →  "Phuket"
  เชียงใหม่ / chiang mai / 清迈 / 치앙마이               →  "Chiang Mai"
  กระบี่  / krabi / 甲米 / 끄라비                        →  "Krabi"
  พัทยา  / pattaya / 芭提雅 / 파타야                     →  "Pattaya"
  หัวหิน  / hua hin / 华欣 / 후아힌                      →  "Hua Hin"
  สุราษฎร์ธานี / surat thani / 素叻他尼                  →  "Surat Thani"
  If unclear → null (never guess).

Date rules (all languages — output YYYY-MM-DD):
  today    / วันนี้ / 今天 / 오늘 / 今日 / hari ini / aujourd'hui / hoy / сегодня   → {TODAY}
  tomorrow / พรุ่งนี้ / 明天 / 내일 / 明日 / besok / demain / mañana / завтра / tmrw → {TOMORROW}
  Specific date like "March 15", "15 มี.ค.", "3월 15일", "15/3", "2026-03-15" → parse to YYYY-MM-DD.
  If no date mentioned → null.

Intent rules:
  reset / start over / เริ่มใหม่ / 重置 / 다시 시작 → "reset"
  help / what can you do                           → "help"
  status / check my booking                        → "status"
  booking / trip request                           → "book"
  Bare digit like "2" alone, or seat selection like "2,3" → "unknown"
"""


def _build_system(tz: str) -> str:
    t   = _today(tz)
    tmr = (t + timedelta(days=1)).isoformat()
    return (
        _SYSTEM
        .replace("{TODAY}", t.isoformat())
        .replace("{TOMORROW}", tmr)
    )


async def extract_intent_and_lang(
    text: str,
    time_zone: str = "Asia/Bangkok",
    http_client: Optional[httpx.AsyncClient] = None,
) -> Dict[str, Any]:
    """Extract intent + language from raw user text.

    Never raises — returns _default() on any error or missing API key.
    """
    key = _api_key()
    if not key:
        return _default()

    payload = {
        "model":      _MODEL,
        "max_tokens": _MAX_TOKENS,
        "system":     _build_system(time_zone),
        "messages":   [{"role": "user", "content": (text or "").strip()}],
    }
    headers = {
        "Content-Type":      "application/json",
        "x-api-key":         key,
        "anthropic-version": "2023-06-01",
    }
    own = http_client is None
    c   = http_client or httpx.AsyncClient(timeout=_TIMEOUT)
    try:
        r = await c.post(_ANTHROPIC_URL, json=payload, headers=headers, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        raw  = "".join(
            b.get("text", "") for b in data.get("content", []) if b.get("type") == "text"
        )
        # Strip accidental markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        parsed = json.loads(raw.strip())
    except Exception as exc:
        log.debug("claude_intent fallback (%s)", exc)
        return _default()
    finally:
        if own:
            await c.aclose()

    return {
        "intent":         str(parsed.get("intent") or "unknown").lower(),
        "from_name":      parsed.get("from_name") or None,
        "to_name":        parsed.get("to_name") or None,
        "departure_date": parsed.get("departure_date") or None,
        "pax":            max(1, int(parsed.get("pax") or 1)),
        "language":       str(parsed.get("language") or "en").lower()[:5],
    }


def _default() -> Dict[str, Any]:
    return {
        "intent":         "unknown",
        "from_name":      None,
        "to_name":        None,
        "departure_date": None,
        "pax":            1,
        "language":       "en",
    }
