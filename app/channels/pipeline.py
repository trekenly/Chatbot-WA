"""Channel-agnostic chat pipeline.

This is the single place where:
  1. Inbound text is normalised & NLP-enriched
  2. Orchestrator is called
  3. ChatEnvelope is assembled from BuyerGuide output

All channel webhook handlers call `run_pipeline()` — they only differ in how
they parse inbound messages and render the resulting ChatEnvelope.
"""

from __future__ import annotations

import inspect
import json
import re
from datetime import datetime, timedelta
from typing import Any, Dict, Optional
from zoneinfo import ZoneInfo

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

_SCHEDULE_WORDS = {"schedule", "timetable", "times", "time", "departures",
                   "departure", "trips", "buses"}
_DATE_SPACED_RE = re.compile(r"^\s*(\d{4})\s+(\d{1,2})\s+(\d{1,2})\s*$")


def init_pipeline(busx: BusXClient) -> None:
    """Call once at app startup."""
    global _busx, _orch
    _busx = busx
    _orch = Orchestrator(busx)


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
    """
    if _orch is None:
        raise RuntimeError("Pipeline not initialised — call init_pipeline() first.")

    st_in: Dict[str, Any] = incoming_state if isinstance(incoming_state, dict) else {}
    has_from = st_in.get("from_keyword_id")
    has_to = st_in.get("to_keyword_id")
    has_date = st_in.get("departure_date")

    # ── NLP pre-processing ──────────────────────────────────────────────────
    raw_text = _normalize_date_text(text)
    enriched_text = raw_text

    # "schedule" shortcut when route+date already known
    if _is_schedule_intent(raw_text) and has_from and has_to and has_date:
        pax = st_in.get("pax") or 1
        enriched_text = f"{has_date} {pax} pax"

    # "Bangkok to Phuket" — hold TO until FROM disambiguated
    from_text, to_text = extract_from_to(raw_text)
    if from_text and to_text and not has_from:
        enriched_text = from_text
        _PENDING_TO[user_id] = to_text

    extra: Dict[str, Any] = {
        "locale": locale,
        "time_zone": time_zone,
        "currency": currency,
        "state": incoming_state,
    }
    safe_extra = _filter_kwargs(_orch.handle, extra)

    # ── Orchestrator call ────────────────────────────────────────────────────
    resp: ChatResponse = await _orch.handle(user_id, enriched_text, **safe_extra)
    st = resp.state or {}

    # ── Auto-apply pending TO ────────────────────────────────────────────────
    pending_to = _PENDING_TO.get(user_id)
    if pending_to and st.get("from_keyword_id") and not st.get("to_keyword_id"):
        _PENDING_TO.pop(user_id, None)
        extra2 = {**extra, "state": st}
        safe_extra2 = _filter_kwargs(_orch.handle, extra2)
        resp = await _orch.handle(user_id, pending_to, **safe_extra2)
        st = resp.state or {}

    # ── Force date prompt if route complete but date missing ─────────────────
    if _should_force_ask_date(st):
        prompt = "What travel date? (YYYY-MM-DD, or 'today' / 'tomorrow')"
        force_resp = ChatResponse(
            actions=[Action(type="ask", payload={"field": "departure_date", "prompt": prompt})],
            state=st,
        )
        guided = _guide.render(force_resp)
        return _envelope_from_guided(guided, force_resp)

    guided = _guide.render(resp)
    return _envelope_from_guided(guided, resp)

# Public helper aliases for legacy callers (behavior unchanged).
is_schedule_intent = _is_schedule_intent
normalize_date_text = _normalize_date_text
filter_kwargs = _filter_kwargs
envelope_from_guided = _envelope_from_guided


