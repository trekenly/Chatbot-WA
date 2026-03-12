# app/main.py
from __future__ import annotations

from dotenv import load_dotenv

load_dotenv()

import hashlib
import hmac
import json
import os
import re
import tempfile
import time as _time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Type

try:
    from PIL import Image, ImageDraw, ImageFont
except Exception:
    Image = ImageDraw = ImageFont = None

import httpx
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse, RedirectResponse, PlainTextResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles

from app.busx.auth import get_access_token
from app.busx.client import BusXClient
from app.busx.intent_api import router as intent_router
from app.core.buyer_guide import BuyerGuide
from app.core.contracts import Action, Ask, AskOption, ChatEnvelope, ChatResponse, InboundChat
from app.core.orchestrator import Orchestrator
from app.core.text_extract import extract_from_to
from app.channels.pipeline import init_pipeline, is_schedule_intent as _is_schedule_intent, normalize_date_text as _normalize_date_text, filter_kwargs as _filter_kwargs_for_callable, envelope_from_guided as _envelope_from_guided
from app.whatsapp.payloads import build_whatsapp_payload_from_guided, build_whatsapp_payloads_from_guided
from app.whatsapp.helpers import parse_whatsapp_inbound as _parse_whatsapp_inbound, whatsapp_text_from_guided as _whatsapp_text_from_guided, make_wa_upload_media, wa_image_payload as _wa_image_payload
from app.seatmap.seatmap import extract_available_seats as _extract_available_seats, recommended_seats as _recommended_seats, seatmap_image_file as _seatmap_image_file

app = FastAPI(title="BusX Chatbot", version="0.1.0")

# Serve static dev UI (place buyer.html in app/static/)
app.mount("/static", StaticFiles(directory="app/static"), name="static")

# Optional: serve the React web build (if present).
#
# Production recommendation is still:
#   - Nginx serves the React build (frontend-web/dist)
#   - Nginx proxies /buyer/* to FastAPI
#
# This mount is a convenience for single-binary deployments.
try:
    _react_dist = os.path.join(os.path.dirname(__file__), "..", "frontend-web", "dist")
    _react_dist = os.path.abspath(_react_dist)
    if os.path.isdir(_react_dist):
        app.mount("/web", StaticFiles(directory=_react_dist, html=True), name="web")
except Exception:
    # If dist is missing, ignore.
    pass

# Intent/schema validation endpoints (LLM integration uses these)
app.include_router(intent_router)

busx = BusXClient()
orch = Orchestrator(busx)
guide = BuyerGuide()

# When user writes "Bangkok to Phuket", hold TO until FROM is resolved.
_PENDING_TO_BY_USER: Dict[str, str] = {}

def _get_tzinfo(tz_name: str | None = None):
    """Use fixed UTC+7 for Bangkok without requiring tzdata/zoneinfo."""
    return timezone(timedelta(hours=7))


def _tomorrow_yyyy_mm_dd(tz: str) -> str:
    try:
        now = datetime.now(_get_tzinfo(tz))
    except Exception:
        now = datetime.now()
    return (now.date() + timedelta(days=1)).strftime("%Y-%m-%d")




def _to_bool(v: Any) -> bool:
    """Robust truthiness for JSON payloads (fixes 'false' string being truthy)."""
    if isinstance(v, bool):
        return v
    if v is None:
        return False
    if isinstance(v, (int, float)):
        return v != 0
    if isinstance(v, str):
        s = v.strip().lower()
        if s in {"1", "true", "t", "yes", "y", "on"}:
            return True
        if s in {"0", "false", "f", "no", "n", "off", ""}:
            return False
    return False


def _pydantic_fields(model_cls: Type[Any]) -> set[str]:
    if hasattr(model_cls, "model_fields"):  # pydantic v2
        return set(getattr(model_cls, "model_fields").keys())
    if hasattr(model_cls, "__fields__"):  # pydantic v1
        return set(getattr(model_cls, "__fields__").keys())
    return set()


def _build_model(model_cls: Type[Any], payload: Dict[str, Any]) -> Any:
    fields = _pydantic_fields(model_cls)
    kwargs = {k: payload[k] for k in fields if k in payload}
    return model_cls(**kwargs)


def _should_force_ask_date(state: Dict[str, Any]) -> bool:
    """
    Force an explicit date prompt when:
      - route complete (FROM+TO set)
      - departure_date missing
      - not currently waiting for a numbered choice
      - and we haven't already loaded trips
    """
    if not isinstance(state, dict):
        return False

    if not state.get("from_keyword_id") or not state.get("to_keyword_id"):
        return False

    if state.get("departure_date"):
        return False

    # Avoid overriding disambiguation steps
    if state.get("awaiting_choice"):
        return False

    trips = state.get("trips") or []
    if isinstance(trips, list) and len(trips) > 0:
        return False

    return True


@app.exception_handler(Exception)
async def all_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"error": str(exc), "type": exc.__class__.__name__},
    )


@app.get("/")
async def root():
    # Prefer the React web app when built; otherwise fall back to the vanilla prototype.
    try:
        import os

        _react_dist = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "frontend-web", "dist"))
        if os.path.isdir(_react_dist):
            return RedirectResponse(url="/web")
    except Exception:
        pass
    return RedirectResponse(url="/static/buyer.html")


@app.get("/healthz")
async def healthz():
    return {"ok": True}


@app.get("/debug/token")
async def debug_token():
    async with httpx.AsyncClient() as client:
        token = await get_access_token(client)
        return {"access_token": token[:10] + "..."}  # don’t print full token


async def _handle_chat_core(payload: Dict[str, Any], request: Request) -> ChatResponse:
    if "user_id" not in payload or "text" not in payload:
        raise ValueError("Missing required fields: 'user_id' and/or 'text'.")

    req = _build_model(InboundChat, payload)

    locale = payload.get("locale", "en_US")
    time_zone = payload.get("time_zone", "Asia/Bangkok")
    currency = payload.get("currency", "THB")
    incoming_state = payload.get("state")

    st_in: Dict[str, Any] = incoming_state if isinstance(incoming_state, dict) else {}
    has_from = st_in.get("from_keyword_id")
    has_to = st_in.get("to_keyword_id")
    has_date = st_in.get("departure_date")

    # Normalize date-ish input like "2026 02 14"
    raw_text = _normalize_date_text(req.text)

    enriched_text = raw_text

    # "schedule" keyword:
    # If route complete and date already exists, refresh trips for that date+pax.
    # If date missing, we'll force-ask date after route is complete.
    if _is_schedule_intent(raw_text) and has_from and has_to and has_date:
        pax = st_in.get("pax") or 1
        enriched_text = f"{has_date} {pax} pax"

    # Sentence parsing for "from X to Y"
    from_text, to_text = extract_from_to(raw_text)
    if from_text and to_text and not has_from:
        enriched_text = from_text
        _PENDING_TO_BY_USER[req.user_id] = to_text

    # intent_only mode (safe testing)
    if _to_bool(payload.get("intent_only")):
        base_url = str(request.base_url).rstrip("/")

        parse_body = {
            "text": req.text,
            "locale": locale,
            "time_zone": time_zone,
            "currency": currency,
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            r1 = await client.post(f"{base_url}/busx/intent/parse", json=parse_body)
            r1.raise_for_status()
            parsed = r1.json()
            envelope = parsed.get("intent_envelope") or {}

            r2 = await client.post(f"{base_url}/busx/intent/validate", json=envelope)
            if r2.status_code == 422:
                raise ValueError(json.dumps(r2.json()))
            r2.raise_for_status()

        pretty = json.dumps(envelope, ensure_ascii=False, indent=2)
        return ChatResponse(
            actions=[Action(type="say", payload={"text": pretty})],
            state={"intent_envelope": envelope, "state_in": incoming_state},
        )

    # normal orchestrator flow
    intent_envelope: Optional[dict] = None
    enriched_text = req.text

    # If the UI is submitting a structured form step (e.g., passenger details),
    # DO NOT run NLP normalization. Pass through to orchestrator as-is.
    incoming_step = None
    if isinstance(payload.get("state"), dict):
        incoming_step = payload.get("state", {}).get("step")
    elif isinstance(payload.get("incoming_state"), dict):
        incoming_step = payload.get("incoming_state", {}).get("step")

    def _looks_like_passenger_details(text: str) -> bool:
        if not isinstance(text, str):
            return False
        t = text.strip()
        if not t:
            return False
        if t.startswith("{") and any(k in t.lower() for k in ["\"first\"", "\"last\"", "\"email\"", "\"phone\""]):
            return True
        return False

    _COMMAND_WORDS = {
        "reset", "restart", "start over",
        "help", "show", "status", "details", "detail", "info", "payinfo",
        "confirm", "ok", "okay", "yes", "y",
        "reserve", "reservation", "book", "booking", "hold",
        "pay", "payment", "checkout",
    }

    def _is_command(text: str) -> bool:
        return text.strip().lower() in _COMMAND_WORDS

    if _to_bool(payload.get("use_intent")) and incoming_step not in {"DETAILS", "PASSENGER_DETAILS"} and not _looks_like_passenger_details(req.text) and not _is_command(req.text):
        base_url = str(request.base_url).rstrip("/")

        parse_body = {
            "text": req.text,
            "locale": locale,
            "time_zone": time_zone,
            "currency": currency,
        }

        async with httpx.AsyncClient(timeout=20.0) as client:
            r1 = await client.post(f"{base_url}/busx/intent/parse", json=parse_body)
            r1.raise_for_status()
            parsed = r1.json()
            intent_envelope = parsed.get("intent_envelope") or {}

            # Preserve missing fields (we do NOT want schema validation errors for incomplete input).
            missing_fields = parsed.get("missing_fields") or []
            if missing_fields and isinstance(intent_envelope, dict):
                intent_envelope["missing_fields"] = list(missing_fields)

            # Only validate when complete; otherwise orchestrator will ask for missing fields.
            if not missing_fields:
                r2 = await client.post(f"{base_url}/busx/intent/validate", json=intent_envelope)
                if r2.status_code == 422:
                    raise ValueError(json.dumps(r2.json()))
                r2.raise_for_status()

        trip = (intent_envelope.get("payload") or {}).get("trip_search") or {}
        dep_date = trip.get("departure_date")
        adult_count = (trip.get("passengers") or {}).get("adult_count")

        from_name = (trip.get("from") or {}).get("name")
        to_name = (trip.get("to") or {}).get("name")

        # IMPORTANT: keep any extracted route info in the enriched text.
        parts = []
        if from_name and to_name:
            parts.append(f"{from_name} to {to_name}")
        elif from_name:
            parts.append(str(from_name))
        elif to_name:
            parts.append(str(to_name))

        if dep_date:
            parts.append(str(dep_date))
        if adult_count:
            parts.append(f"{adult_count} pax")

        if parts:
            enriched_text = " ".join(parts)

    extra: Dict[str, Any] = {
        "locale": locale,
        "time_zone": time_zone,
        "currency": currency,
        "state": incoming_state,
        "intent_envelope": intent_envelope,
    }
    safe_extra = _filter_kwargs_for_callable(orch.handle, extra)

    # 1) First call
    resp = await orch.handle(req.user_id, enriched_text, **safe_extra)
    st = resp.state or {}

    # 2) Auto-apply pending TO after FROM disambiguation
    pending_to = _PENDING_TO_BY_USER.get(req.user_id)
    if pending_to and st.get("from_keyword_id") and not st.get("to_keyword_id"):
        _PENDING_TO_BY_USER.pop(req.user_id, None)

        extra2 = dict(extra)
        extra2["state"] = st
        safe_extra2 = _filter_kwargs_for_callable(orch.handle, extra2)

        resp = await orch.handle(req.user_id, pending_to, **safe_extra2)
        st = resp.state or {}

    # 3) FORCE DATE PROMPT (avoid double-render):
    # Return ONLY an "ask" action (no "say"), because BuyerGuide turns ask into the visible message.
    if _should_force_ask_date(st):
        prompt = "What travel date? (YYYY-MM-DD, or say 'today' / 'tomorrow')"
        return ChatResponse(
            actions=[Action(type="ask", payload={"field": "departure_date", "prompt": prompt})],
            state=st,
        )

    return resp


@app.post("/chat")
async def chat(payload: Dict[str, Any], request: Request):
    try:
        resp = await _handle_chat_core(payload, request)
        return resp.model_dump()
    except ValueError as e:
        return JSONResponse(status_code=422, content={"error": str(e)})


@app.post("/buyer/chat")
async def buyer_chat(payload: Dict[str, Any], request: Request):
    try:
        resp = await _handle_chat_core(payload, request)
        guided = guide.render(resp)
        # Build the new, typed envelope (ask.field is authoritative for the UI).
        ask_obj = None
        if isinstance(guided.expect, dict) and guided.expect.get("type") == "field":
            ask_obj = Ask(type="field", field=str(guided.expect.get("field") or ""), prompt=guided.message)
        elif isinstance(guided.expect, dict) and guided.expect.get("type") == "choice":
            options: list[AskOption] = []
            for item in guided.menu or []:
                i = str(item.get("i"))
                label = str(item.get("label") or i)
                desc = str(item.get("description") or "").strip() or None
                options.append(AskOption(value=i, label=label, description=desc))
            ask_obj = Ask(type="choice", field="choice", prompt=guided.message, options=options)
        elif isinstance(guided.expect, dict) and guided.expect.get("type") == "seatmap":
            seats_raw = guided.expect.get("seats")
            # seats can be either a list of seat numbers OR a full layout object (dict)
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

        env = ChatEnvelope(
            say=guided.message,
            ask=ask_obj,
            actions=resp.actions or [],
            state=guided.state or {},
            # legacy
            message=guided.message,
            menu=guided.menu,
            expect=guided.expect,
        )
        return env.model_dump()
    except ValueError as e:
        return JSONResponse(status_code=422, content={"error": str(e)})


@app.post("/buyer/reservation_details")
async def buyer_reservation_details(payload: Dict[str, Any]):
    """Helper endpoint for Buyer UI to refresh payment details."""
    try:
        state = payload.get("state") or {}
        booking_id = payload.get("booking_id") or state.get("reservation_id")
        if not booking_id:
            return JSONResponse(status_code=422, content={"error": "reservation_id (booking_id) missing"})

        details = await busx.get_reservation_details(booking_id=str(booking_id))
        return JSONResponse(content=details)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})




@app.post("/buyer/get_tickets")
async def buyer_get_tickets(payload: Dict[str, Any]):
    """Fetch tickets for a booking (JSON format)."""
    try:
        state = payload.get("state") or {}
        booking_id = payload.get("booking_id") or state.get("reservation_id") or state.get("booking_id")
        if not booking_id:
            return JSONResponse(status_code=422, content={"error": "booking_id missing"})
        ticket_format = payload.get("ticket_format") or "json"
        resp = await busx.get_tickets(booking_id=str(booking_id), ticket_format=str(ticket_format))
        return JSONResponse(content=resp)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/ticket/{booking_id}")
async def view_ticket(booking_id: str):
    """Proxy the BusX HTML e-ticket — used by WhatsApp CTA URL button."""
    from app.busx import endpoints as _ep
    try:
        token = await busx._token()
        params = {
            "access_token": token,
            "locale": "en_US",
            "booking_id": str(booking_id),
            "ticket_format": "html",
        }
        async with httpx.AsyncClient(timeout=30.0) as client:
            r = await client.get(_ep.GET_TICKETS, params=params)
        if r.status_code >= 400:
            return HTMLResponse(content=f"<p>Ticket not available (HTTP {r.status_code})</p>", status_code=r.status_code)
        return HTMLResponse(content=r.text)
    except Exception as exc:
        return HTMLResponse(content=f"<p>Could not fetch ticket: {exc}</p>", status_code=500)


@app.post("/buyer/unmark_seats")
async def buyer_unmark_seats(payload: Dict[str, Any]):
    """Release held seats for a fare_ref_id + seat_event_ids (best-effort)."""
    try:
        state = payload.get("state") or {}
        fare_ref_id = payload.get("fare_ref_id") or state.get("selected_fare_ref_id")
        seat_event_ids = payload.get("seat_event_ids") or state.get("seat_event_ids") or []
        if not fare_ref_id or not seat_event_ids:
            return JSONResponse(status_code=422, content={"error": "fare_ref_id and seat_event_ids required"})
        resp = await busx.unmark_seats(fare_ref_id=str(fare_ref_id), seat_event_ids=[str(x) for x in seat_event_ids])
        return JSONResponse(content=resp)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/buyer/search_trips")
async def buyer_search_trips(payload: Dict[str, Any]):
    """Search trips (wrapper for UI rebooking flows)."""
    try:
        from_id = int(payload.get("from_keyword_id"))
        to_id = int(payload.get("to_keyword_id"))
        departure_date = str(payload.get("departure_date"))
        pax = int(payload.get("pax") or 1)
        resp = await busx.search_trips(
            journey_type="one_way",
            departure_date=departure_date,
            from_keyword_id=from_id,
            to_keyword_id=to_id,
            currency=payload.get("currency") or "THB",
        )
        return JSONResponse(content=resp)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


# --- Bangkok terminal sellable filter (frontend helper) ---
# The frontend shows a Bangkok terminal picker. When destination+date are known,
# we probe BusX search_trips for each terminal and return only those that actually
# have sellable routes for that destination/date. This avoids showing terminals
# that cannot sell the selected destination.
import asyncio
import difflib
from functools import lru_cache

def _norm_key(s: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]+", " ", (s or "").lower())).strip()

_BKK_TERMINALS = [
    {"id": "mochit", "query": "Bangkok Mo Chit"},
    {"id": "ekkamai", "query": "Bangkok Ekkamai"},
    {"id": "saitai", "query": "Bangkok Sai Tai Mai"},
    {"id": "rangsit", "query": "Bangkok Rangsit"},
]

@lru_cache(maxsize=4)
def _bkk_terminal_queries() -> Dict[str, str]:
    return {t["id"]: t["query"] for t in _BKK_TERMINALS}

def _best_row_for_query(rows: list, query: str) -> Optional[dict]:
    """
    Choose the best keyword row for a Bangkok terminal query.

    Important: list_keyword_from contains a generic row for Bangkok (keyword_type=state_province)
    with keyword_name="Bangkok". A naive substring match would incorrectly select that for every
    terminal query (because "bangkok" is contained in "bangkok mochit", etc.). We therefore:
      - Prefer keyword_type in {"stop","station"} when the query includes terminal tokens
      - Require terminal token presence in the candidate name (when possible)
      - Use scoring (no early-return on substring) with a length penalty for short/generic names
    """
    q = _norm_key(query)
    if not q:
        return None

    # terminal tokens (normalized) besides "bangkok"
    terminal_tokens = []
    for tok in ["mochit", "mo chit", "ekkamai", "saitaimai", "sai tai mai", "rangsit"]:
        kt = _norm_key(tok)
        if kt and kt in q and kt not in {"bangkok"}:
            terminal_tokens.append(kt)

    def row_name(r: dict) -> str:
        return str(r.get("keyword_name") or r.get("state_province_name") or "")

    # If query includes a terminal token, first try a strict filter over stop/station rows in Bangkok
    if terminal_tokens:
        strict = []
        for r in rows:
            if not isinstance(r, dict):
                continue
            if str(r.get("state_province_name") or "").strip().lower() != "bangkok":
                continue
            kt = str(r.get("keyword_type") or "").strip().lower()
            if kt not in {"stop", "station"}:
                continue
            nk = _norm_key(row_name(r))
            if not nk:
                continue
            if all(t in nk for t in terminal_tokens):
                strict.append(r)

        # Prefer the longest name (most specific) among strict matches
        if strict:
            strict.sort(key=lambda r: len(_norm_key(row_name(r))), reverse=True)
            return strict[0]

    # Fallback: score all rows, but penalize overly-generic matches
    best = None
    best_score = 0.0

    for r in rows:
        if not isinstance(r, dict):
            continue
        name = row_name(r)
        nk = _norm_key(name)
        if not nk:
            continue

        score = difflib.SequenceMatcher(a=q, b=nk).ratio()

        # bonus if name contains terminal tokens
        if terminal_tokens and all(t in nk for t in terminal_tokens):
            score += 0.10

        # penalty for very short/generic names (prevents selecting "Bangkok" for every query)
        if len(nk) <= 8:   # "bangkok" is 7
            score -= 0.15

        # tiny bonus for more specific (longer) matches when scores tie
        score += min(len(nk) / 200.0, 0.05)

        if score > best_score:
            best_score = score
            best = r

    if best is not None and best_score >= 0.82:
        return best
    return None
    best = None
    best_score = 0.0
    for r in rows:
        name = str(r.get("keyword_name") or r.get("state_province_name") or "")
        nk = _norm_key(name)
        if not nk:
            continue
        # strong fast path
        if nk == q or nk in q or q in nk:
            return r
        score = difflib.SequenceMatcher(a=q, b=nk).ratio()
        if score > best_score:
            best_score = score
            best = r
    # require a decent similarity to avoid wrong terminal ids
    if best is not None and best_score >= 0.82:
        return best
    return None


@app.post("/buyer/bkk_sellable_terminals")
async def buyer_bkk_sellable_terminals(payload: Dict[str, Any]):
    """Return Bangkok terminal IDs that have sellable trips to the given destination/date.

    This endpoint is used ONLY to filter the Bangkok terminal picker UI.
    Requirements:
      - Must never block boot/flow: bounded timeouts + fast failure
      - If inputs are missing, try to read from in-memory session state (by user_id)
      - Fail-open: if anything goes wrong, return [] so the UI can fall back to static mapping
    """
    try:
        user_id = str(payload.get("user_id") or "").strip() or None
        to_id = payload.get("to_keyword_id")
        departure_date = payload.get("departure_date")
        locale = payload.get("locale") or "en_US"
        currency = payload.get("currency") or "THB"

        # If caller didn't provide ids (frontend may not have them), pull from orchestrator session.
        if (not to_id or not departure_date) and user_id:
            s = orch.sessions.get(user_id)
            if s:
                to_id = to_id or getattr(s, "to_keyword_id", None)
                departure_date = departure_date or getattr(s, "departure_date", None)

        if not to_id or not departure_date:
            return JSONResponse(content={"success": True, "sellable_terminal_ids": []})

        to_id = int(to_id)
        departure_date = str(departure_date)

        # Fetch keyword catalog once
        rows_resp = await busx.list_keyword_from(locale=locale)
        rows = (rows_resp or {}).get("data") if isinstance(rows_resp, dict) else None
        if not isinstance(rows, list):
            return JSONResponse(content={"success": True, "sellable_terminal_ids": []})

        def _row_name(r: dict) -> str:
            return str(r.get("keyword_name") or r.get("state_province_name") or "")

        def _nk(s: str) -> str:
            return _norm_key(s)

        # Prefer keyword_type=stop/station for terminals, and match by distinctive tokens.
        # (Do NOT allow generic 'Bangkok' province row to win.)
        terminal_rows: list[tuple[str, int]] = []
        for tid in _bkk_terminal_queries().keys():
            wanted_tokens: list[str] = []
            if tid == "saitai":
                wanted_tokens = ["southern", "sai", "tai"]
            elif tid == "mochit":
                wanted_tokens = ["mo", "chit"]  # sometimes "mo chit", sometimes "mochit"
            elif tid == "ekkamai":
                wanted_tokens = ["ekkamai"]
            elif tid == "rangsit":
                wanted_tokens = ["rangsit"]

            best = None
            best_score = -1.0

            for r in rows:
                if not isinstance(r, dict):
                    continue
                kt = str(r.get("keyword_type") or "").strip().lower()
                if kt not in {"stop", "station"}:
                    continue
                name = _row_name(r)
                nk = _nk(name)
                if "bangkok" not in nk and tid != "rangsit":
                    # most terminal rows still contain 'Bangkok'
                    continue
                # token match
                tok_hits = 0
                for t in wanted_tokens:
                    if t in nk:
                        tok_hits += 1
                if wanted_tokens and tok_hits == 0:
                    continue

                # scoring: token hits + similarity bonus
                score = float(tok_hits)
                score += difflib.SequenceMatcher(a=_nk(tid), b=nk).ratio() * 0.25
                score += min(len(nk) / 300.0, 0.10)  # slight preference for longer names
                # penalize generic rows
                if nk == "bangkok":
                    score -= 2.0

                if score > best_score:
                    best_score = score
                    best = r

            if best and best.get("keyword_id"):
                terminal_rows.append((tid, int(best["keyword_id"])))

        async def _probe(tid: str, from_kw_id: int) -> Optional[str]:
            try:
                resp = await asyncio.wait_for(
                    busx.search_trips(
                        journey_type="one_way",
                        departure_date=departure_date,
                        from_keyword_id=int(from_kw_id),
                        to_keyword_id=int(to_id),
                        currency=currency,
                    ),
                    timeout=2.5,
                )
                if not isinstance(resp, dict) or resp.get("success") is not True:
                    return None
                data = resp.get("data")
                if isinstance(data, dict):
                    dep = data.get("departure")
                    if isinstance(dep, list) and len(dep) > 0:
                        return tid
                return None
            except Exception:
                return None

        # Probe in parallel with bounded latency
        tasks = [_probe(tid, fid) for tid, fid in terminal_rows]
        done = await asyncio.gather(*tasks, return_exceptions=False)
        sellable = [x for x in done if isinstance(x, str)]
        return JSONResponse(content={"success": True, "sellable_terminal_ids": sellable})
    except Exception:
        return JSONResponse(content={"success": True, "sellable_terminal_ids": []})
# Fail open: frontend will fallback to static mapping
        return JSONResponse(status_code=200, content={"success": True, "sellable_terminal_ids": [], "error": str(e)})

@app.post("/buyer/manage_open_ended")
async def buyer_manage_open_ended(payload: Dict[str, Any]):
    """Convert ticket(s) in a booking to open-ended if allowed."""
    try:
        state = payload.get("state") or {}
        booking_id = payload.get("booking_id") or state.get("reservation_id") or state.get("booking_id")
        if not booking_id:
            return JSONResponse(status_code=422, content={"error": "booking_id missing"})

        details = await busx.get_reservation_details(booking_id=str(booking_id))
        # Extract global ticket numbers (best-effort)
        gtns = []
        try:
            data = details.get("data") if isinstance(details, dict) else None
            reservations = None
            if isinstance(data, dict):
                reservations = data.get("reservations") or data.get("reservation_details")
            if isinstance(reservations, list):
                for r in reservations:
                    g = r.get("global_ticket_number") if isinstance(r, dict) else None
                    if g:
                        gtns.append(str(g))
        except Exception:
            pass

        if not gtns:
            return JSONResponse(status_code=422, content={"error": "No global_ticket_number found for this booking"})

        req = await busx.request_open_ended_ticket(global_ticket_numbers=gtns)
        data = req.get("data") if isinstance(req, dict) else None
        open_ids = []
        allow = False
        if isinstance(data, list):
            for it in data:
                if (str(it.get("allow_open") or "").upper() == "Y") and it.get("open_ref_id"):
                    allow = True
                    open_ids.append(str(it["open_ref_id"]))
        if not allow or not open_ids:
            return JSONResponse(content={"success": True, "allow_open": "N", "request": req})

        created = await busx.create_open_ended_ticket(open_ref_ids=open_ids)
        return JSONResponse(content={"success": True, "allow_open": "Y", "request": req, "create": created})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/buyer/manage_set_travel_date")
async def buyer_manage_set_travel_date(payload: Dict[str, Any]):
    """Set a new travel date by rebooking to a new fare_ref_id."""
    try:
        state = payload.get("state") or {}
        booking_id = payload.get("booking_id") or state.get("reservation_id") or state.get("booking_id")
        new_fare_ref_id = payload.get("new_fare_ref_id")
        if not booking_id or not new_fare_ref_id:
            return JSONResponse(status_code=422, content={"error": "booking_id and new_fare_ref_id required"})

        details = await busx.get_reservation_details(booking_id=str(booking_id))
        old_list = []
        try:
            data = details.get("data") if isinstance(details, dict) else None
            reservations = None
            if isinstance(data, dict):
                reservations = data.get("reservations") or data.get("reservation_details")
            if isinstance(reservations, list):
                for r in reservations:
                    if not isinstance(r, dict):
                        continue
                    g = r.get("global_ticket_number")
                    ev = r.get("seat_event_id") or r.get("seat_eventid")
                    if g and ev:
                        old_list.append({"global_ticket_number": str(g), "seat_event_id": str(ev)})
        except Exception:
            pass

        if not old_list:
            return JSONResponse(status_code=422, content={"error": "Missing global_ticket_number/seat_event_id in reservation details"})

        req = await busx.request_set_travel_date(new_fare_ref_id=str(new_fare_ref_id), old_global_ticket_numbers=old_list)
        # Extract rebooking_ref_ids where allow_rebooking=Y
        rebook_ids = []
        data = req.get("data") if isinstance(req, dict) else None
        if isinstance(data, list):
            for it in data:
                if str(it.get("allow_rebooking") or "").upper() == "Y" and it.get("rebooking_ref_id"):
                    rebook_ids.append(str(it["rebooking_ref_id"]))
        if not rebook_ids:
            return JSONResponse(content={"success": True, "allow_rebooking": "N", "request": req})

        created = await busx.create_set_travel_date(rebooking_ref_ids=rebook_ids)
        return JSONResponse(content={"success": True, "allow_rebooking": "Y", "request": req, "create": created})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/buyer/cancel_reservation")
async def buyer_cancel_reservation(payload: Dict[str, Any]):
    """Cancel a reservation (pre-ticket) using booking_id."""
    try:
        state = payload.get("state") or {}
        booking_id = payload.get("booking_id") or state.get("reservation_id")
        if not booking_id:
            return JSONResponse(status_code=422, content={"error": "booking_id missing"})

        resp = await busx.cancel_reservations(booking_id=str(booking_id))
        return JSONResponse(content=resp)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/buyer/request_refund")
async def buyer_request_refund(payload: Dict[str, Any]):
    """Request refund details for a ticket (returns allow_refund + amounts)."""
    try:
        gtn = payload.get("global_ticket_number")
        if not gtn:
            return JSONResponse(status_code=422, content={"error": "global_ticket_number missing"})
        resp = await busx.request_refunds(global_ticket_numbers=[str(gtn)])
        return JSONResponse(content=resp)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.post("/buyer/create_refund")
async def buyer_create_refund(payload: Dict[str, Any]):
    """Create refunds given a refund_ref_id."""
    try:
        rref = payload.get("refund_ref_id")
        if not rref:
            return JSONResponse(status_code=422, content={"error": "refund_ref_id missing"})
        resp = await busx.create_refunds(refund_ref_ids=[str(rref)])
        return JSONResponse(content=resp)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})


@app.get("/debug/keywords/from")
async def debug_keywords_from():
    return JSONResponse(content=await busx.list_keyword_from())


@app.get("/debug/keywords/to")
async def debug_keywords_to(from_keyword_id: int):
    return JSONResponse(content=await busx.list_keyword_to(from_keyword_id=from_keyword_id))


@app.post("/debug/search_trips")
async def debug_search_trips(payload: dict):
    return JSONResponse(content=await busx.search_trips(**payload))


@app.on_event("startup")
async def _startup_init_pipeline():
    init_pipeline(busx)


@app.on_event("shutdown")
async def _shutdown():
    await busx.close()

# --- WhatsApp webhook support ---
WA_VERIFY_TOKEN = (os.getenv("WHATSAPP_VERIFY_TOKEN") or "").strip()
WA_ACCESS_TOKEN = (os.getenv("WHATSAPP_ACCESS_TOKEN") or "").strip()
WA_PHONE_NUMBER_ID = (os.getenv("WHATSAPP_PHONE_NUMBER_ID") or "").strip()
WA_API_VERSION = (os.getenv("WHATSAPP_API_VERSION") or "v19.0").strip()
WA_APP_SECRET = (os.getenv("WHATSAPP_APP_SECRET") or "").strip()

_WA_STATE_BY_USER: Dict[str, Dict[str, Any]] = {}
_WA_STATE_MAX_USERS = 10_000  # evict oldest when exceeded

_WA_SEEN_MSG_IDS: set = set()
_WA_SEEN_MSG_IDS_MAX = 500
_WA_LAST_PROCESSED: Dict[str, float] = {}
_WA_DEDUP_WINDOW_SEC = 5.0

# Rate limiting: max messages per user per window
_WA_RATE_COUNTS: Dict[str, list] = {}  # user_id -> [timestamps]
_WA_RATE_LIMIT = 30       # max messages
_WA_RATE_WINDOW_SEC = 60  # per 60 seconds

_WA_MAX_TEXT_LEN = 2000   # discard messages longer than this


_wa_upload_media = make_wa_upload_media(WA_ACCESS_TOKEN, WA_PHONE_NUMBER_ID, WA_API_VERSION)

@app.get("/channels/whatsapp/webhook")
async def whatsapp_verify(request: Request):
    params = request.query_params
    hub_mode = params.get("hub.mode", "")
    hub_verify_token = params.get("hub.verify_token", "")
    hub_challenge = params.get("hub.challenge", "")
    if hub_mode == "subscribe" and WA_VERIFY_TOKEN and hub_verify_token == WA_VERIFY_TOKEN:
        return PlainTextResponse(hub_challenge)
    raise HTTPException(status_code=403, detail="Verification failed")


@app.post("/channels/whatsapp/webhook")
async def whatsapp_webhook(request: Request):
    raw_body = await request.body()

    # 1. Webhook signature verification (skip if APP_SECRET not configured)
    if WA_APP_SECRET:
        sig_header = request.headers.get("X-Hub-Signature-256", "")
        expected = "sha256=" + hmac.new(
            WA_APP_SECRET.encode(), raw_body, hashlib.sha256
        ).hexdigest()
        if not hmac.compare_digest(sig_header, expected):
            raise HTTPException(status_code=403, detail="Invalid signature")

    try:
        body = json.loads(raw_body)
    except Exception:
        return {"status": "ok", "ignored": True}

    parsed = _parse_whatsapp_inbound(body)
    print(f"WA inbound parsed={parsed}")
    if not parsed:
        print(f"WA inbound ignored (unparseable): {json.dumps(body)[:300]}")
        return {"status": "ok", "ignored": True}

    user_id = parsed["user_id"]
    text = parsed["text"]
    print(f"WA inbound user={user_id} text={text!r}")

    # 2. Input length cap
    if len(text) > _WA_MAX_TEXT_LEN:
        return {"status": "ok", "ignored": True, "reason": "too_long"}

    # 3. Per-user rate limiting
    _now = _time.monotonic()
    _buckets = _WA_RATE_COUNTS.setdefault(user_id, [])
    _WA_RATE_COUNTS[user_id] = [t for t in _buckets if _now - t < _WA_RATE_WINDOW_SEC]
    if len(_WA_RATE_COUNTS[user_id]) >= _WA_RATE_LIMIT:
        return {"status": "ok", "ignored": True, "reason": "rate_limited"}
    _WA_RATE_COUNTS[user_id].append(_now)

    # 4. Dedup by msg_id
    msg_id = parsed.get("msg_id") or ""
    if msg_id:
        if msg_id in _WA_SEEN_MSG_IDS:
            return {"status": "ok", "ignored": True, "reason": "duplicate"}
        _WA_SEEN_MSG_IDS.add(msg_id)
        if len(_WA_SEEN_MSG_IDS) > _WA_SEEN_MSG_IDS_MAX:
            evict = list(_WA_SEEN_MSG_IDS)[:_WA_SEEN_MSG_IDS_MAX // 2]
            for m in evict:
                _WA_SEEN_MSG_IDS.discard(m)

    state = dict(_WA_STATE_BY_USER.get(user_id) or {})

    # 5. Dedup by (user, step, text) within time window
    # Skip dedup for reset/commands — always process them
    _WA_RESET_WORDS = {"reset", "restart", "start over", "begin", "start"}
    _dedup_key = f"{user_id}:{state.get('step', '')}:{text.strip().lower()}"
    if text.strip().lower() not in _WA_RESET_WORDS:
        _last_t = _WA_LAST_PROCESSED.get(_dedup_key)
        if _last_t is not None and (_now - _last_t) < _WA_DEDUP_WINDOW_SEC:
            print(f"WA dedup blocked: key={_dedup_key!r}")
            return {"status": "ok", "ignored": True, "reason": "duplicate_window"}
    _WA_LAST_PROCESSED[_dedup_key] = _now
    print(f"WA processing: step={state.get('step','NEW')!r} text={text!r}")

    # 6. Cap session store size
    if user_id not in _WA_STATE_BY_USER and len(_WA_STATE_BY_USER) >= _WA_STATE_MAX_USERS:
        oldest = next(iter(_WA_STATE_BY_USER))
        del _WA_STATE_BY_USER[oldest]

    # 7. "Other date" button — send format hint without touching session state
    if text.strip() == "__pick_date__":
        from datetime import date as _date_today
        _example = (_date_today.today() + __import__("datetime").timedelta(days=9)).isoformat()
        _hint_body = f"Please type your travel date in this format:\nYYYY-MM-DD\n\nExample: {_example}"
        _hint_payloads = [{"messaging_product": "whatsapp", "to": user_id, "type": "text", "text": {"body": _hint_body}}]
        if not WA_ACCESS_TOKEN or not WA_PHONE_NUMBER_ID:
            return {"status": "ok", "outbound": "skipped_missing_config"}
        _hint_url = f"https://graph.facebook.com/{WA_API_VERSION}/{WA_PHONE_NUMBER_ID}/messages"
        _hint_headers = {"Authorization": f"Bearer {WA_ACCESS_TOKEN}", "Content-Type": "application/json"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                r = await client.post(_hint_url, json=_hint_payloads[0], headers=_hint_headers)
            return {"status": "ok", "meta_status": r.status_code}
        except Exception as exc:
            print(f"WhatsApp pick_date hint error: {exc}")
            return {"status": "ok"}

    try:
        resp = await _handle_chat_core({
            "user_id": user_id,
            "text": text,
            "state": state,
            "locale": "en_US",
            "time_zone": "Asia/Bangkok",
            "currency": "THB",
        }, request)
        guided = guide.render(resp)
        _new_state = guided.state or {}
        _WA_STATE_BY_USER[user_id] = _new_state
        payloads = await build_whatsapp_payloads_from_guided(
            guided,
            user_id,
            text_from_guided=lambda g: _whatsapp_text_from_guided(g, _extract_available_seats, _recommended_seats),
            extract_available_seats=_extract_available_seats,
            recommended_seats=_recommended_seats,
            seatmap_image_file=_seatmap_image_file,
            upload_media=_wa_upload_media,
            image_payload_factory=_wa_image_payload,
        )
        # Append CTA e-ticket button when payment is first confirmed
        _prev_step = state.get("step", "")
        _new_reservation_id = _new_state.get("reservation_id", "")
        if _prev_step != "PAID" and _new_state.get("step") == "PAID" and _new_reservation_id:
            _ticket_url = str(request.base_url).rstrip("/") + f"/ticket/{_new_reservation_id}"
            payloads.append({
                "messaging_product": "whatsapp",
                "to": user_id,
                "type": "interactive",
                "interactive": {
                    "type": "cta_url",
                    "body": {"text": "Your e-ticket is ready. Tap below to view or save it."},
                    "action": {
                        "name": "cta_url",
                        "parameters": {
                            "display_text": "View e-ticket",
                            "url": _ticket_url,
                        },
                    },
                },
            })
    except Exception as exc:
        print(f"WhatsApp handler error: {type(exc).__name__}: {exc}")
        payloads = [{"messaging_product": "whatsapp", "to": user_id, "type": "text", "text": {"body": "Sorry, something went wrong. Please try again or type 'reset'."}}]

    if not WA_ACCESS_TOKEN or not WA_PHONE_NUMBER_ID:
        print("WhatsApp outbound skipped: missing token or phone number id")
        return {"status": "ok", "outbound": "skipped_missing_config", "payload_preview": payloads[:1]}

    url = f"https://graph.facebook.com/{WA_API_VERSION}/{WA_PHONE_NUMBER_ID}/messages"
    headers = {
        "Authorization": f"Bearer {WA_ACCESS_TOKEN}",
        "Content-Type": "application/json",
    }
    statuses = []
    try:
        async with httpx.AsyncClient(timeout=30.0) as client:
            for payload in payloads:
                r = await client.post(url, json=payload, headers=headers)
                statuses.append(r.status_code)
                print(f"WhatsApp outbound status={r.status_code}")
                if r.status_code >= 400:
                    print(f"WhatsApp outbound body={r.text}")
        return {"status": "ok", "meta_status": statuses[-1] if statuses else 200, "all_statuses": statuses}
    except Exception as exc:
        print(f"WhatsApp outbound exception: {exc}")
        return {"status": "ok", "meta_status": "exception", "detail": str(exc)}
