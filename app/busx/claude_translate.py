"""app/busx/claude_translate.py
──────────────────────────────
Translate a ChatEnvelope's user-facing text into the user's detected language
using a single Claude Haiku call.

What IS translated:
  • envelope.say / message          — main reply text
  • envelope.ask.prompt             — input prompt shown to user
  • envelope.ask.options[].label    — choice option labels (non-numeric)
  • envelope.ask.options[].description
  • envelope.menu[].label / description

What is NEVER translated:
  • ask.type, ask.field             — machine-readable; frontend depends on these
  • ask.options[].value             — values sent back to the server
  • Any line matching "snake_case_key: value"
    (e.g. "reservation_id: ABC123", "pay_status: N")
    — frontend parsers depend on these being in English
  • The exact phrase "Reservation created."
    — triggers parseReservationCard() in the frontend
  • Dates (2026-03-15), times (08:00), prices (350.00 THB, ฿350)
  • Seat codes / numbers

Graceful degradation:
  • ANTHROPIC_API_KEY missing  → returns envelope unchanged
  • API call fails / times out → returns envelope unchanged
"""
from __future__ import annotations

import json
import logging
import os
import re
from copy import deepcopy
from typing import Any, Dict, List, Optional

import httpx

from app.core.contracts import Ask, AskOption, ChatEnvelope

log = logging.getLogger(__name__)

_ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
_MODEL         = "claude-haiku-4-5-20251001"
_TIMEOUT       = 10.0
_MAX_TOKENS    = 4096   # enough for a full translated envelope

# ── Language display names (for the prompt) ───────────────────────────────────

_LANG_NAMES: Dict[str, str] = {
    "th": "Thai",
    "ja": "Japanese",
    "zh": "Chinese (Simplified)",
    "ko": "Korean",
    "ru": "Russian",
    "ar": "Arabic",
    "de": "German",
    "fr": "French",
    "es": "Spanish",
    "vi": "Vietnamese",
    "id": "Indonesian",
    "ms": "Malay",
}


def _api_key() -> Optional[str]:
    k = os.getenv("ANTHROPIC_API_KEY", "").strip()
    return k if k else None


# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM = """\
You are a professional translator for a bus-ticket booking chatbot.
Translate the provided JSON array of strings into {LANGUAGE}.
Return ONLY a valid JSON array of the SAME length — no explanation, no markdown, no extra items.

Critical rules (apply to every string):
- CRITICAL: The output array MUST have exactly the same number of items as the input array.
  Never split one input string into multiple output strings.
  If a string contains \\n newlines, translate it as a SINGLE string preserving all \\n.
- IMPORTANT: Any line that matches the pattern "snake_case_key: value"
  (e.g. "reservation_id: ABC123", "pay_status: N", "trip_id: 12345",
  "booking_ref: XYZ", "seat: 12") must be kept EXACTLY as-is.
- IMPORTANT: Keep the exact phrase "Reservation created." in English always.
- Keep dates (e.g. 2026-03-15), times (e.g. 08:00, 14:30),
  prices (e.g. 350.00 THB, ฿350), and seat/ticket numbers unchanged.
- Keep numeric-only strings unchanged.
- Keep divider lines (e.g. ─────────────────) unchanged.
- Keep proper nouns and place names unchanged (e.g. Sai Tai Mai, Mo Chit 2, Phuket Bus Terminal).
- Keep email addresses, phone numbers, and booking reference codes unchanged.
- Translate all natural-language prompts, labels, and descriptions.
- Preserve line breaks (\\n) and WhatsApp markdown (*bold*, _italic_).
"""


def _build_system(lang: str) -> str:
    name = _LANG_NAMES.get(lang, lang.upper())
    return _SYSTEM.replace("{LANGUAGE}", name)


# ── Claude API call ───────────────────────────────────────────────────────────

async def _translate_texts(
    texts: List[str],
    lang: str,
    http_client: Optional[httpx.AsyncClient] = None,
) -> Optional[List[str]]:
    """Send a list of strings to Claude for translation.

    Returns a same-length list of translated strings, or None on failure.
    """
    key = _api_key()
    if not key or not texts:
        return None

    payload = {
        "model":      _MODEL,
        "max_tokens": _MAX_TOKENS,
        "system":     _build_system(lang),
        "messages":   [{
            "role":    "user",
            "content": json.dumps(texts, ensure_ascii=False),
        }],
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
        # Strip markdown fences
        raw = re.sub(r"^```(?:json)?\s*", "", raw.strip())
        raw = re.sub(r"\s*```$", "", raw)
        raw = raw.strip()

        # Robustly locate the JSON array even if Claude adds preamble text
        m = re.search(r"\[.*\]", raw, re.DOTALL)
        if not m:
            log.warning("claude_translate: no JSON array found in response (lang=%r, texts_count=%d)", lang, len(texts))
            return None
        result = json.loads(m.group(0))
        if isinstance(result, list) and len(result) == len(texts):
            return [str(t) for t in result]
        log.warning(
            "claude_translate: result length mismatch expected=%d got=%d (lang=%r)",
            len(texts), len(result) if isinstance(result, list) else -1, lang,
        )
        return None
    except Exception as exc:
        log.warning("claude_translate failed (lang=%r): %s", lang, exc)
        return None
    finally:
        if own:
            await c.aclose()


# ── Public API ────────────────────────────────────────────────────────────────

async def translate_envelope(
    env: ChatEnvelope,
    lang: str,
    http_client: Optional[httpx.AsyncClient] = None,
) -> ChatEnvelope:
    """Translate all user-facing text in env into lang.

    Returns the original env unchanged if lang=="en", API key missing,
    or any error occurs.
    """
    if not lang or lang == "en":
        return env

    key = _api_key()
    if not key:
        return env

    # ── Collect translatable segments (path, text) ──────────────────────────
    segments: List[tuple] = []   # (path_key, text)

    if env.say:
        segments.append(("say", env.say))

    if env.ask and env.ask.prompt and env.ask.prompt != env.say:
        segments.append(("ask_prompt", env.ask.prompt))

    if env.ask and env.ask.options:
        for i, opt in enumerate(env.ask.options):
            lbl = (opt.label or "").strip()
            if lbl and not lbl.isdigit():
                segments.append((f"opt_{i}_label", lbl))
            desc = (opt.description or "").strip()
            if desc:
                segments.append((f"opt_{i}_desc", desc))

    if env.menu:
        for i, item in enumerate(env.menu):
            lbl = str(item.get("label") or "").strip()
            if lbl and not lbl.isdigit():
                segments.append((f"menu_{i}_label", lbl))
            desc = str(item.get("description") or "").strip()
            if desc:
                segments.append((f"menu_{i}_desc", desc))

    if not segments:
        return env

    texts = [s[1] for s in segments]
    translated = await _translate_texts(texts, lang, http_client)

    if not translated:
        return env

    # ── Apply translations back ───────────────────────────────────────────────
    # Work on a mutable copy so we never mutate the original.
    env_dict: Dict[str, Any] = env.model_dump()

    for (path_key, orig_text), translation in zip(segments, translated):
        if path_key == "say":
            env_dict["say"] = translation
            env_dict["message"] = translation
            # Also update ask.prompt if it was identical to say — render_whatsapp
            # uses ask.prompt as the button/message body, so it must be translated.
            ask = env_dict.get("ask")
            if isinstance(ask, dict) and ask.get("prompt") == orig_text:
                ask["prompt"] = translation

        elif path_key == "ask_prompt":
            ask = env_dict.get("ask")
            if isinstance(ask, dict):
                ask["prompt"] = translation

        elif path_key.startswith("opt_") and path_key.endswith("_label"):
            i = int(path_key.split("_")[1])
            ask = env_dict.get("ask")
            if isinstance(ask, dict):
                opts = ask.get("options") or []
                if i < len(opts):
                    opts[i]["label"] = translation

        elif path_key.startswith("opt_") and path_key.endswith("_desc"):
            i = int(path_key.split("_")[1])
            ask = env_dict.get("ask")
            if isinstance(ask, dict):
                opts = ask.get("options") or []
                if i < len(opts):
                    opts[i]["description"] = translation

        elif path_key.startswith("menu_") and path_key.endswith("_label"):
            i = int(path_key.split("_")[1])
            menu = env_dict.get("menu") or []
            if i < len(menu):
                menu[i]["label"] = translation

        elif path_key.startswith("menu_") and path_key.endswith("_desc"):
            i = int(path_key.split("_")[1])
            menu = env_dict.get("menu") or []
            if i < len(menu):
                menu[i]["description"] = translation

    try:
        return ChatEnvelope(**env_dict)
    except Exception as exc:
        log.warning("claude_translate: failed to rebuild envelope (%s)", exc)
        return env
