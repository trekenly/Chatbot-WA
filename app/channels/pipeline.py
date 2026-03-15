"""Channel-agnostic chat pipeline.

This is the single place where:
  1. Inbound text is normalised & NLP-enriched (including Claude intent)
  2. Language is detected and persisted in state
  3. Orchestrator is called
  4. ChatEnvelope is assembled from BuyerGuide output
  5. Bot reply is translated into the user's language

All channel webhook handlers call `run_pipeline()` — they only differ in how
they parse inbound messages and render the resulting ChatEnvelope.
"""

from __future__ import annotations

import inspect
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

log = logging.getLogger(__name__)

from app.busx.client import BusXClient
from app.core.buyer_guide import BuyerGuide
from app.core.contracts import (
    Action, Ask, AskOption, ChatEnvelope, ChatResponse, InboundChat
)
from app.core.orchestrator import Orchestrator
from app.core.text_extract import extract_from_to

# ── Singletons (initialised once at startup) ────────────────────────────────
_busx: Optional[BusXClient] = None
_orch: Optional[Orchestrator] = None
_guide = BuyerGuide()

# Pending TO cache: when user says "Bangkok to Phuket" we hold the TO until
# FROM disambiguation is resolved.
_PENDING_TO: Dict[str, str] = {}

# Pending DATE cache: when user gives route+date in one shot on a fresh session,
# we send the route to the orchestrator first, then auto-apply the date once
# from_keyword_id and to_keyword_id are both resolved.
_PENDING_DATE: Dict[str, str] = {}

_SCHEDULE_WORDS = {"schedule", "timetable", "times", "time", "departures",
                   "departure", "trips", "buses"}
_DATE_SPACED_RE = re.compile(r"^\s*(\d{4})\s+(\d{1,2})\s+(\d{1,2})\s*$")

# ── Picker-step guard ─────────────────────────────────────────────────────────
# When the user is mid-flow selecting seats/trips/details, don't run Claude
# intent enrichment — a reply like "2,3" would get misread as pax=2.
_PICKER_STEPS = {"PICK_SEATS", "PICK_TRIP", "MARKED", "DETAILS", "READY"}

# Special intents that always bypass the picker guard.
_SPECIAL_RE = re.compile(r"\b(reset|help|status)\b", re.IGNORECASE)

# ── Unicode language heuristic (fallback when Claude is unavailable) ──────────
_UNICODE_RANGES = [
    (re.compile(r"[\u0E00-\u0E7F]"),               "th"),
    (re.compile(r"[\u3040-\u30FF]"),               "ja"),
    (re.compile(r"[\u4E00-\u9FFF]"),               "zh"),
    (re.compile(r"[\u0400-\u04FF]"),               "ru"),
    (re.compile(r"[\u0600-\u06FF]"),               "ar"),
    (re.compile(r"[\uAC00-\uD7AF\u1100-\u11FF]"), "ko"),
]


def _detect_lang_unicode(text: str) -> Optional[str]:
    for pat, lang in _UNICODE_RANGES:
        if pat.search(text or ""):
            return lang
    return None


def init_pipeline(busx: BusXClient, orchestrator: Optional[Orchestrator] = None) -> None:
    """Call once at app startup.

    Pass an existing ``orchestrator`` instance to share it with other callers
    (e.g. the ``_handle_chat_core`` path in main.py).  When omitted a new
    Orchestrator is created from *busx*.
    """
    global _busx, _orch
    _busx = busx
    _orch = orchestrator if orchestrator is not None else Orchestrator(busx)


def get_orchestrator() -> Orchestrator:
    if _orch is None:
        raise RuntimeError("Pipeline not initialised — call init_pipeline() first.")
    return _orch


# ── Internal helpers ─────────────────────────────────────────────────────────

def _is_schedule_intent(text: str) -> bool:
    t = (text or "").strip().lower()
    if t in _SCHEDULE_WORDS:
        return True
    return any(t.startswith(w + " ") for w in _SCHEDULE_WORDS)


def _normalize_date_text(text: str) -> str:
    t = (text or "").strip()
    m = _DATE_SPACED_RE.match(t)
    if m:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}-{int(m.group(3)):02d}"
    return text


def _filter_kwargs(fn, kwargs: dict) -> dict:
    try:
        sig = inspect.signature(fn)
        params = sig.parameters.values()
        if any(p.kind == inspect.Parameter.VAR_KEYWORD for p in params):
            return kwargs
        accepted = {p.name for p in params}
        return {k: v for k, v in kwargs.items() if k in accepted}
    except Exception:
        return kwargs


def _should_force_ask_date(state: Dict[str, Any]) -> bool:
    if not isinstance(state, dict):
        return False
    if not state.get("from_keyword_id") or not state.get("to_keyword_id"):
        return False
    if state.get("departure_date"):
        return False
    if state.get("awaiting_choice"):
        return False
    trips = state.get("trips") or []
    if isinstance(trips, list) and trips:
        return False
    return True


def _envelope_from_guided(guided, resp: ChatResponse) -> ChatEnvelope:
    """Convert BuyerGuide output into a typed ChatEnvelope."""
    ask_obj: Optional[Ask] = None

    if isinstance(guided.expect, dict):
        etype = guided.expect.get("type")

        if etype == "field":
            ask_obj = Ask(
                type="field",
                field=str(guided.expect.get("field") or ""),
                prompt=guided.message,
            )

        elif etype == "choice":
            options: list[AskOption] = []
            for item in guided.menu or []:
                i = str(item.get("i"))
                label = str(item.get("label") or i)
                desc = (str(item.get("description") or "")).strip() or None
                options.append(AskOption(value=i, label=label, description=desc))
            ask_obj = Ask(
                type="choice",
                field="choice",
                prompt=guided.message,
                options=options,
            )

        elif etype == "seatmap":
            seats_raw = guided.expect.get("seats")
            seats = seats_raw
            if isinstance(seats_raw, list):
                seats = [str(x) for x in seats_raw]
            selected = [str(x) for x in (guided.expect.get("selected") or [])]
            pax_raw = guided.expect.get("pax")
            pax = int(pax_raw) if str(pax_raw or "").isdigit() else None
            ask_obj = Ask(
                type="seatmap",
                field="seats",
                prompt=guided.message or "Choose seats",
                seats=seats,
                pax=pax,
                selected=selected,
            )

    return ChatEnvelope(
        say=guided.message,
        ask=ask_obj,
        actions=resp.actions or [],
        state=guided.state or {},
        # legacy shims
        message=guided.message,
        menu=guided.menu,
        expect=guided.expect,
    )


# ── Public entry point ────────────────────────────────────────────────────────

async def run_pipeline(
    user_id: str,
    text: str,
    incoming_state: Optional[Dict[str, Any]] = None,
    locale: str = "en_US",
    time_zone: str = "Asia/Bangkok",
    currency: str = "THB",
) -> ChatEnvelope:
    """Run the full chat pipeline for any channel.

    Args:
        user_id:        Unique ID for this user (phone number, PSID, etc.)
        text:           Raw user message text
        incoming_state: Server state from previous turn (None for messaging
                        channels that use StateStore)
        locale:         BCP-47 locale hint for NLP
        time_zone:      IANA tz (default Asia/Bangkok)
        currency:       ISO 4217 (default THB)

    Returns:
        ChatEnvelope ready to be rendered by a channel adapter.
        envelope.state["chat_language"] persists the detected language so
        the next turn can respond in the same language even if the user
        replies with a bare number.
    """
    if _orch is None:
        raise RuntimeError("Pipeline not initialised — call init_pipeline() first.")

    st_in: Dict[str, Any] = incoming_state if isinstance(incoming_state, dict) else {}
    has_from = st_in.get("from_keyword_id")
    has_to   = st_in.get("to_keyword_id")
    has_date = st_in.get("departure_date")
    log.warning("DIAG state: from=%r to=%r date=%r step=%r",
                has_from, has_to, has_date, st_in.get("step"))

    # ── Language: read from persisted state first ────────────────────────────
    _detected_lang: str = st_in.get("chat_language", "en") or "en"

    # ── NLP pre-processing ───────────────────────────────────────────────────
    raw_text     = _normalize_date_text(text)
    enriched_text = raw_text

    current_step = st_in.get("step", "")
    is_picker    = current_step in _PICKER_STEPS
    is_special   = bool(_SPECIAL_RE.search(raw_text or ""))

    # ── Claude intent enrichment ─────────────────────────────────────────────
    # Skip for picker steps (seat / trip selection) unless it's a special
    # command like reset/help/status — those must always fire.
    if not is_picker or is_special:
        try:
            from app.busx.claude_intent import extract_intent_and_lang
            intent_data = await extract_intent_and_lang(raw_text, time_zone)
            log.warning("DIAG intent=%r lang=%r from=%r to=%r date=%r",
                        intent_data.get("intent"), intent_data.get("language"),
                        intent_data.get("from_name"), intent_data.get("to_name"),
                        intent_data.get("departure_date"))

            # Update language — priority order:
            #   1. Form input (name/email/phone): always keep persisted language.
            #      A Chinese user entering "Eric Kenly" or "0826464693" (Thai
            #      phone) must still get a Chinese reply.
            #   2. Claude says non-English → use detected language.
            #   3. Claude says English AND text has real letters → user switched
            #      to English (covers "reset", route names, commands, etc.).
            #   4. Pure digits/symbols → ambiguous; keep persisted language so a
            #      Thai user tapping "1" still gets a Thai reply.
            _STICKY_STEPS = {"DETAILS_NAME", "DETAILS_EMAIL", "DETAILS_PHONE"}
            lang = intent_data.get("language", "en") or "en"
            if current_step in _STICKY_STEPS:
                # Form field input (name/email/phone) — never flip language.
                # The user is typing a name, email or phone number; the NLP
                # language guess is meaningless here (e.g. a Thai phone number
                # "0826464693" looks Thai to Claude even in an English session).
                # Keep whatever language was in effect before this step.
                pass
            elif lang != "en":
                _detected_lang = lang
            elif any(c.isalpha() for c in raw_text):
                # Text contains actual letters and Claude says English → English
                _detected_lang = "en"
            else:
                # Pure digits/punctuation — keep persisted language for context
                uni_lang = _detect_lang_unicode(raw_text)
                if uni_lang:
                    _detected_lang = uni_lang

            # Build enriched_text from extracted entities
            intent = intent_data.get("intent", "unknown")
            if intent == "book":
                from_name      = intent_data.get("from_name")
                to_name        = intent_data.get("to_name")
                departure_date = intent_data.get("departure_date")
                pax            = intent_data.get("pax", 1)
                parts = []

                # Fresh state (no route/date in state yet): the orchestrator
                # can't parse "Bangkok to Phuket 2026-03-14" as a single input
                # — it resolves the route but drops the date.  Send route first;
                # stash the date in _PENDING_DATE and apply it automatically
                # after from_keyword_id + to_keyword_id are both resolved
                # (mirrors the _PENDING_TO pattern).
                is_fresh = not has_from and not has_to and not has_date

                if is_fresh and departure_date and (from_name or to_name):
                    if from_name and to_name:
                        enriched_text = f"{from_name} to {to_name}"
                    elif from_name:
                        enriched_text = from_name
                    else:
                        enriched_text = to_name  # type: ignore[assignment]
                    if pax and pax > 1:
                        enriched_text += f" {pax} pax"
                    _PENDING_DATE[user_id] = departure_date
                else:
                    # Mid-flow or fresh-with-date-only: build normally
                    include_route = not (has_from and has_to)
                    if include_route:
                        if from_name and to_name:
                            parts.append(f"{from_name} to {to_name}")
                        elif from_name:
                            parts.append(from_name)
                        elif to_name:
                            parts.append(to_name)
                    if departure_date:
                        parts.append(departure_date)
                    if pax and pax > 1:
                        parts.append(f"{pax} pax")
                    if parts:
                        enriched_text = " ".join(parts)
            log.warning("DIAG enriched_text=%r detected_lang=%r", enriched_text, _detected_lang)

        except Exception as _exc:
            log.warning("DIAG claude_intent EXCEPTION: %s", _exc)
            # Graceful degradation: fall through with raw_text and unicode
            uni_lang = _detect_lang_unicode(raw_text)
            if uni_lang and _detected_lang == "en":
                _detected_lang = uni_lang
    else:
        # Inside picker steps: just apply unicode heuristic (no Claude call)
        uni_lang = _detect_lang_unicode(raw_text)
        if uni_lang and _detected_lang == "en":
            _detected_lang = uni_lang

    # ── Legacy enrichments (still useful when Claude intent yields nothing) ──

    # "schedule" shortcut when route+date already known
    if _is_schedule_intent(enriched_text) and has_from and has_to and has_date:
        pax = st_in.get("pax") or 1
        enriched_text = f"{has_date} {pax} pax"

    # "Bangkok to Phuket" — hold TO until FROM disambiguated
    from_text, to_text = extract_from_to(enriched_text)
    if from_text and to_text and not has_from:
        enriched_text = from_text
        _PENDING_TO[user_id] = to_text

    extra: Dict[str, Any] = {
        "locale":    locale,
        "time_zone": time_zone,
        "currency":  currency,
        "state":     incoming_state,
    }
    safe_extra = _filter_kwargs(_orch.handle, extra)

    # ── Orchestrator call ────────────────────────────────────────────────────
    resp: ChatResponse = await _orch.handle(user_id, enriched_text, **safe_extra)
    st = resp.state or {}

    # ── Auto-apply pending TO ─────────────────────────────────────────────────
    pending_to = _PENDING_TO.get(user_id)
    if pending_to and st.get("from_keyword_id") and not st.get("to_keyword_id"):
        _PENDING_TO.pop(user_id, None)
        extra2 = {**extra, "state": st}
        safe_extra2 = _filter_kwargs(_orch.handle, extra2)
        resp = await _orch.handle(user_id, pending_to, **safe_extra2)
        st = resp.state or {}

    # ── Auto-apply pending DATE ───────────────────────────────────────────────
    # Fires after route is fully resolved (both IDs present) but date is missing.
    pending_date = _PENDING_DATE.get(user_id)
    if pending_date and st.get("from_keyword_id") and st.get("to_keyword_id") and not st.get("departure_date"):
        _PENDING_DATE.pop(user_id, None)
        extra3 = {**extra, "state": st}
        safe_extra3 = _filter_kwargs(_orch.handle, extra3)
        resp = await _orch.handle(user_id, pending_date, **safe_extra3)
        st = resp.state or {}

    # ── Auto-load destinations list when FROM is known but TO is not ─────────
    # When the orchestrator returns "Where to?" as a plain-text ask (e.g. after
    # the user just picked a date) AND the default FROM is already set in the
    # session, make a follow-up call with "" so _ensure_to_selected triggers
    # _discover_viable_tos_for_from → returns the full interactive choice list.
    if (st.get("from_keyword_id") and
            not st.get("to_keyword_id") and
            not st.get("desired_to_text") and
            st.get("awaiting_choice") is None and
            st.get("departure_date")):
        extra_dest = {**extra, "state": st}
        safe_dest = _filter_kwargs(_orch.handle, extra_dest)
        dest_resp = await _orch.handle(user_id, "", **safe_dest)
        dest_st = dest_resp.state or {}
        if dest_st.get("awaiting_choice") == "to" and dest_st.get("pending_to_candidates"):
            log.warning("DIAG auto-loaded destinations: %d options", len(dest_st.get("pending_to_candidates", [])))
            resp = dest_resp
            st = dest_st

    # ── Force date prompt if route complete but date missing ─────────────────
    if _should_force_ask_date(st):
        # Plain English — translate_envelope auto-translates to any language.
        # No quoted today/tomorrow hints (translators treat quoted words as literals).
        # WhatsApp date buttons already show today/tomorrow in the user's language.
        prompt = "When would you like to travel?"
        force_resp = ChatResponse(
            actions=[Action(type="ask", payload={"field": "departure_date", "prompt": prompt})],
            state=st,
        )
        guided = _guide.render(force_resp)
        env = _envelope_from_guided(guided, force_resp)
    else:
        guided = _guide.render(resp)
        env = _envelope_from_guided(guided, resp)

    # ── Persist detected language in state ───────────────────────────────────
    if _detected_lang and _detected_lang != "en":
        env.state["chat_language"] = _detected_lang
    else:
        # User is in English — clear any persisted non-English language so the
        # next turn doesn't inherit it.
        env.state.pop("chat_language", None)

    # ── Translate reply into user's language ─────────────────────────────────
    log.warning("DIAG final detected_lang=%r, will_translate=%r", _detected_lang, _detected_lang not in (None, "en"))
    if _detected_lang and _detected_lang != "en":
        try:
            from app.busx.claude_translate import translate_envelope
            env = await translate_envelope(env, _detected_lang)
        except Exception as _exc:
            log.warning("DIAG translate_envelope EXCEPTION: %s", _exc)

    return env


# Public helper aliases for legacy callers (behavior unchanged).
is_schedule_intent  = _is_schedule_intent
normalize_date_text = _normalize_date_text
filter_kwargs       = _filter_kwargs
envelope_from_guided = _envelope_from_guided
