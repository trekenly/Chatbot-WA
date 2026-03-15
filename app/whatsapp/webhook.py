"""
app/whatsapp/webhook.py
────────────────────────
WhatsApp Business Cloud API webhook.

Plug into your existing app with exactly two lines in main.py:

    from app.whatsapp.webhook import router as whatsapp_router
    app.include_router(whatsapp_router)

How it works:
  1. Meta sends POST /whatsapp/webhook when a customer messages you
  2. We extract phone number + message text
  3. Load that phone's session state (in-memory, keyed by phone)
  4. Call _handle_chat_core() directly — same function /buyer/chat calls
  5. Run BuyerGuide.render() — same renderer the web UI uses
  6. Format for WhatsApp:
       ≤ 3 choices  →  interactive button message  (tap to reply)
       4–10 choices →  interactive list message     (scrollable)
       > 10 choices →  plain numbered text list
       seatmap      →  available seat numbers + instructions
       plain text   →  text message
  7. POST reply to Meta Cloud API
  8. Return 200 immediately (Meta requires < 15 s; processing is backgrounded)

Zero changes to orchestrator.py, buyer_guide.py, contracts.py, or BusX client.

Required .env variables:
    WHATSAPP_TOKEN            Access token from Meta Developer Console
    WHATSAPP_PHONE_NUMBER_ID  Numeric phone number ID from Meta
    WHATSAPP_VERIFY_TOKEN     Any secret string you choose (for webhook verification)

Optional:
    WHATSAPP_REDIS_URL        e.g. redis://localhost:6379
                              If set, sessions survive server restarts.
                              If not set, sessions live in RAM (fine for single-process).
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Dict, List, Optional

import httpx
from fastapi import APIRouter, BackgroundTasks, HTTPException, Request
from fastapi.responses import PlainTextResponse

log = logging.getLogger(__name__)

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])

_GRAPH = "https://graph.facebook.com/v19.0"
_SESSION_TTL = 60 * 60 * 4  # 4 hours idle → conversation resets


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


# ─── Session store ────────────────────────────────────────────────────────────
# Stores the orchestrator state dict per phone number.
# Identical to what the React frontend holds in browser state.

_mem: Dict[str, Dict[str, Any]] = {}


def _get_state(phone: str) -> Dict[str, Any]:
    redis_url = _env("WHATSAPP_REDIS_URL")
    if redis_url:
        try:
            import redis as _r
            raw = _r.from_url(redis_url, decode_responses=True).get(f"wa:{phone}")
            return json.loads(raw) if raw else {}
        except Exception as e:
            log.warning("Redis get failed, using memory: %s", e)

    s = _mem.get(phone)
    if not s:
        return {}
    if time.time() - s.get("ts", 0) > _SESSION_TTL:
        _mem.pop(phone, None)
        return {}
    return s.get("state", {})


def _set_state(phone: str, state: Dict[str, Any]) -> None:
    redis_url = _env("WHATSAPP_REDIS_URL")
    if redis_url:
        try:
            import redis as _r
            _r.from_url(redis_url, decode_responses=True).setex(
                f"wa:{phone}", _SESSION_TTL, json.dumps(state)
            )
            return
        except Exception as e:
            log.warning("Redis set failed, using memory: %s", e)

    _mem[phone] = {"state": state, "ts": time.time()}


# ─── WhatsApp Cloud API sender ────────────────────────────────────────────────

async def _send(
    phone_number_id: str,
    token: str,
    to: str,
    *,
    text: Optional[str] = None,
    interactive: Optional[Dict[str, Any]] = None,
) -> None:
    url     = f"{_GRAPH}/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    if interactive:
        body: Dict[str, Any] = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "interactive",
            "interactive": interactive,
        }
    else:
        body = {
            "messaging_product": "whatsapp",
            "recipient_type": "individual",
            "to": to,
            "type": "text",
            "text": {"body": (text or "")[:4096], "preview_url": False},
        }

    async with httpx.AsyncClient(timeout=12.0) as c:
        r = await c.post(url, json=body, headers=headers)
        if r.status_code not in {200, 201}:
            log.error("WhatsApp send failed %s: %s", r.status_code, r.text[:300])


# ─── Format GuidedTurn → WhatsApp message(s) ─────────────────────────────────

# ─── Core processing ──────────────────────────────────────────────────────────

async def _process(phone: str, user_text: str, phone_number_id: str, token: str) -> None:
    """
    Load session → run pipeline (intent + language + translate) → render → send.
    Runs as a background task so we return 200 to Meta immediately.
    """
    state = _get_state(phone)

    try:
        from app.channels.pipeline import run_pipeline
        from app.channels.render import render_whatsapp

        envelope = await run_pipeline(
            user_id       = f"wa_{phone}",
            text          = user_text,
            incoming_state= state,
            locale        = "en_US",
            time_zone     = "Asia/Bangkok",
            currency      = "THB",
        )

        # Persist state (includes chat_language for next turn)
        _set_state(phone, envelope.state or {})

        # Render the (already-translated) envelope for WhatsApp
        wa_payload = render_whatsapp(envelope, phone)

        if wa_payload.get("type") == "interactive":
            messages: List[Dict[str, Any]] = [
                {"type": "interactive", "interactive": wa_payload["interactive"]}
            ]
        else:
            messages = [
                {"type": "text", "body": (wa_payload.get("text") or {}).get("body", "")}
            ]

    except Exception:
        log.exception("Error processing WA message from %s****", phone[-4:])
        messages = [{
            "type": "text",
            "body": "Sorry, something went wrong. Type *reset* to start over.",
        }]

    for msg in messages:
        try:
            await _send(
                phone_number_id, token, phone,
                text        = msg.get("body")        if msg["type"] == "text"        else None,
                interactive = msg.get("interactive") if msg["type"] == "interactive" else None,
            )
        except Exception:
            log.exception("Failed to send WhatsApp message")


# ─── Webhook endpoints ────────────────────────────────────────────────────────

@router.get("/webhook")
async def verify_webhook(request: Request) -> PlainTextResponse:
    """
    Meta webhook verification — called once when you register the URL.
    Must respond with hub.challenge to confirm ownership.
    """
    if (
        request.query_params.get("hub.mode") == "subscribe"
        and request.query_params.get("hub.verify_token") == _env("WHATSAPP_VERIFY_TOKEN")
    ):
        log.info("WhatsApp webhook verified ✅")
        return PlainTextResponse(request.query_params.get("hub.challenge", ""))
    raise HTTPException(status_code=403, detail="Webhook verification failed")


@router.post("/webhook")
async def receive_webhook(
    request: Request,
    background_tasks: BackgroundTasks,
) -> Dict[str, str]:
    """
    Receive incoming WhatsApp messages from Meta.
    Returns 200 immediately; real work happens in a background task.
    """
    phone_number_id = _env("WHATSAPP_PHONE_NUMBER_ID")
    token           = _env("WHATSAPP_ACCESS_TOKEN") or _env("WHATSAPP_TOKEN")

    try:
        body = await request.json()
    except Exception:
        return {"status": "ok"}

    try:
        entry  = (body.get("entry") or [{}])[0]
        change = (entry.get("changes") or [{}])[0]
        value  = change.get("value") or {}
        msgs   = value.get("messages") or []

        if not msgs:
            return {"status": "ok"}  # delivery receipt / status update — ignore

        msg   = msgs[0]
        phone = msg.get("from", "")
        mtype = msg.get("type", "")

        # Extract user text depending on message type
        user_text = ""
        if mtype == "text":
            user_text = (msg.get("text") or {}).get("body", "").strip()
        elif mtype == "interactive":
            iv = msg.get("interactive") or {}
            if iv.get("type") == "button_reply":
                user_text = iv["button_reply"].get("id", "")
                log.warning("DIAG webhook button_reply id=%r title=%r", iv["button_reply"].get("id", ""), iv["button_reply"].get("title", ""))
            elif iv.get("type") == "list_reply":
                user_text = iv["list_reply"].get("id", "")
                log.warning("DIAG webhook list_reply id=%r title=%r description=%r", iv["list_reply"].get("id", ""), iv["list_reply"].get("title", ""), iv["list_reply"].get("description", ""))
        elif mtype == "button":
            user_text = (msg.get("button") or {}).get("payload", "").strip()

        if phone and user_text:
            log.info("WA ← ****%s: %s", phone[-4:], user_text[:80])
            background_tasks.add_task(
                _process, phone, user_text, phone_number_id, token
            )

    except Exception:
        log.exception("WhatsApp webhook parse error")

    return {"status": "ok"}


# ─── Debug endpoint ───────────────────────────────────────────────────────────

@router.get("/sessions")
async def list_sessions() -> Dict[str, Any]:
    """Active in-memory WhatsApp sessions — useful during development."""
    now = time.time()
    active = [
        {
            "suffix":   f"****{k[-4:]}",
            "step":     v.get("state", {}).get("step", "?"),
            "idle_min": round((now - v.get("ts", now)) / 60, 1),
        }
        for k, v in _mem.items()
        if now - v.get("ts", 0) < _SESSION_TTL
    ]
    return {"active": len(active), "sessions": active}
