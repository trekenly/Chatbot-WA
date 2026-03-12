from __future__ import annotations

import os
from datetime import datetime, timedelta
from typing import Any, Awaitable, Callable, Dict, Optional

from app.formatters.reservation_card import format_reservation_card, parse_reservation_message


def _get_expect_field(guided: Any) -> str:
    expect = getattr(guided, "expect", None) or {}
    if not isinstance(expect, dict):
        return ""
    return str(expect.get("field") or "").strip().lower()


def _wa_text_payload(user_id: str, body: str) -> Dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": user_id,
        "type": "text",
        "text": {"body": body[:4096]},
    }


def _wa_button_payload(user_id: str, body: str, buttons: list[dict]) -> Dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": user_id,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {"buttons": buttons[:3]},
        },
    }


def _normalize_list_rows(rows: list[dict]) -> list[dict]:
    safe_rows = []
    for item in rows[:10]:
        row = {
            "id": str(item.get("id") or "")[:200],
            "title": str(item.get("title") or "")[:24],
        }
        desc = str(item.get("description") or "").strip()
        if desc:
            row["description"] = desc[:72]
        safe_rows.append(row)
    return safe_rows


def _wa_list_payload(user_id: str, body: str, rows: list[dict], button_text: str = "Choose") -> Dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": user_id,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body[:1024]},
            "action": {
                "button": button_text[:20],
                "sections": [{"title": "Options", "rows": _normalize_list_rows(rows)}],
            },
        },
    }


def _wa_flow_payload(user_id: str, body: str, *, flow_id: str, flow_token: str, cta: str = "Open form") -> Dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": user_id,
        "type": "interactive",
        "interactive": {
            "type": "flow",
            "body": {"text": body[:1024]},
            "action": {
                "name": "flow",
                "parameters": {
                    "flow_message_version": "3",
                    "flow_id": str(flow_id),
                    "flow_cta": str(cta)[:20],
                    "flow_token": str(flow_token)[:256],
                    "flow_action": "navigate",
                    "flow_action_payload": {
                        "screen": "PASSENGER_DETAILS",
                        "data": {},
                    },
                },
            },
        },
    }


def _flow_enabled() -> bool:
    return str(os.getenv("WHATSAPP_PASSENGER_FLOW_ENABLED", "")).strip().lower() in {"1", "true", "yes", "on"}


def _flow_id() -> str:
    return (os.getenv("WHATSAPP_PASSENGER_FLOW_ID") or "").strip()


def _flow_cta() -> str:
    return (os.getenv("WHATSAPP_PASSENGER_FLOW_CTA") or "Open form").strip() or "Open form"


def _passenger_flow_payload(user_id: str, body: str) -> Optional[Dict[str, Any]]:
    flow_id = _flow_id()
    if not (flow_id and _flow_enabled()):
        return None
    flow_token = f"passenger:{user_id}"
    return _wa_flow_payload(user_id, body, flow_id=flow_id, flow_token=flow_token, cta=_flow_cta())


def _wa_common_place_rows(kind: str) -> list[dict]:
    if kind == "to":
        return [
            {"id": "Bangkok", "title": "Bangkok", "description": "Capital, airports, shopping, old town, and big transport hub."},
            {"id": "Phuket", "title": "Phuket", "description": "Patong, Kata, Karon, Old Town, ferry piers, beaches, and resort areas."},
            {"id": "Krabi", "title": "Krabi", "description": "Gateway to Ao Nang & Railay, island trips, and beaches."},
            {"id": "Chiang Mai", "title": "Chiang Mai", "description": "Old City, Nimman, mountains, temples, and night markets."},
            {"id": "Pattaya", "title": "Pattaya", "description": "Beach city near Bangkok with hotels, ferries, and nightlife."},
            {"id": "Hua Hin", "title": "Hua Hin", "description": "Quiet beach town with resorts, golf, and weekend travel."},
            {"id": "Surat Thani", "title": "Surat Thani", "description": "Gateway for Koh Samui, Koh Phangan, Koh Tao, and ferries."},
        ]
    return [
        {"id": "Bangkok", "title": "Bangkok", "description": "Main long-distance hub with Sai Tai Mai, Mochit, and Ekkamai."},
        {"id": "Phuket", "title": "Phuket", "description": "Island departures, intercity buses, and onward southern trips."},
        {"id": "Krabi", "title": "Krabi", "description": "Useful for Ao Nang, ferries, and mainland transfers."},
        {"id": "Chiang Mai", "title": "Chiang Mai", "description": "Major northern hub for Chiang Rai, Pai, and mountain routes."},
        {"id": "Pattaya", "title": "Pattaya", "description": "Popular east coast departure point with Bangkok links."},
        {"id": "Hua Hin", "title": "Hua Hin", "description": "Convenient for beach stays south of Bangkok."},
        {"id": "Surat Thani", "title": "Surat Thani", "description": "Important mainland hub for ferry islands and southern routes."},
    ]


def _date_button_title(label: str, dt: datetime) -> str:
    return f"{label} ({dt.strftime('%b')} {dt.day})"


def _date_prompt_payload(user_id: str, message: str) -> Dict[str, Any]:
    now = datetime.now().astimezone()
    tomorrow = now + timedelta(days=1)
    buttons = [
        {"type": "reply", "reply": {"id": now.strftime("%Y-%m-%d"), "title": _date_button_title("Today", now)}},
        {"type": "reply", "reply": {"id": tomorrow.strftime("%Y-%m-%d"), "title": _date_button_title("Tomorrow", tomorrow)}},
        {"type": "reply", "reply": {"id": "__pick_date__", "title": "Other date"}},
    ]
    clean_message = str(message or "").replace(
        "\n\nOr type another date, for example: 2026-03-10", ""
    ).strip()
    return _wa_button_payload(user_id, clean_message, buttons)



def _ticket_count_payload(user_id: str, message: str) -> Dict[str, Any]:
    buttons = [
        {"type": "reply", "reply": {"id": "1", "title": "1 ticket"}},
        {"type": "reply", "reply": {"id": "2", "title": "2 tickets"}},
        {"type": "reply", "reply": {"id": "3", "title": "3 tickets"}},
    ]
    return _wa_button_payload(user_id, message + "\n\nOr type another number.", buttons)


def _confirm_payload(user_id: str, message: str) -> Dict[str, Any]:
    buttons = [
        {"type": "reply", "reply": {"id": "yes", "title": "Confirm"}},
        {"type": "reply", "reply": {"id": "reset", "title": "Start over"}},
    ]
    return _wa_button_payload(user_id, message, buttons)


def _field_prompt_payload(user_id: str, message: str, field: str, low: str) -> Optional[Dict[str, Any]]:
    if field == "departure_date" or "what date" in low or "travel date" in low:
        return _date_prompt_payload(user_id, message)
    if field in {"to", "destination"} or "where are you going" in low:
        return _wa_list_payload(
            user_id,
            message + "\n\nYou can also type another city or terminal.",
            _wa_common_place_rows("to"),
            button_text="Destinations",
        )
    if field in {"from", "departure"} or "where are you departing" in low:
        return _wa_list_payload(
            user_id,
            message + "\n\nYou can also type another city or terminal.",
            _wa_common_place_rows("from"),
            button_text="Departures",
        )
    if field in {"pax", "tickets"} or "how many tickets" in low:
        return _ticket_count_payload(user_id, message)
    if field in {"confirm", "reservation_confirm", "confirmation"} or "reply yes to confirm" in low:
        return _confirm_payload(user_id, message)
    return None


def _menu_payload(user_id: str, message: str, menu: list[dict]) -> Optional[Dict[str, Any]]:
    if not menu:
        return None
    has_desc = any(str(item.get("description") or "").strip() for item in menu)
    long_labels = any(len(str(item.get("label") or "")) > 20 for item in menu)
    if len(menu) <= 3 and not has_desc and not long_labels:
        buttons = []
        for item in menu[:3]:
            buttons.append(
                {"type": "reply", "reply": {"id": str(item.get("i")), "title": str(item.get("label") or item.get("i"))[:20]}}
            )
        return _wa_button_payload(user_id, message, buttons)
    if len(menu) <= 10:
        rows = []
        for item in menu[:10]:
            row = {"id": str(item.get("i")), "title": str(item.get("label") or item.get("i"))[:24]}
            desc = str(item.get("description") or "").strip()
            if desc:
                row["description"] = desc[:72]
            rows.append(row)
        return _wa_list_payload(user_id, message, rows, button_text="Choose")
    return None


def build_whatsapp_payload_from_guided(
    guided: Any,
    user_id: str,
    *,
    text_from_guided: Callable[[Any], str],
) -> Dict[str, Any]:
    message = str(getattr(guided, "message", "") or "").strip() or "OK"
    menu = getattr(guided, "menu", None) or []
    expect = getattr(guided, "expect", None) or {}
    etype = str(expect.get("type") or "")
    field = _get_expect_field(guided)
    low = message.lower()

    if etype == "passenger_flow":
        payload = _passenger_flow_payload(user_id, message)
        if payload is not None:
            return payload

    if etype == "field":
        payload = _field_prompt_payload(user_id, message, field, low)
        if payload is not None:
            return payload

    payload = _menu_payload(user_id, message, menu)
    if payload is not None:
        return payload

    payload = _reservation_card_payload(user_id, message)
    if payload is not None:
        return payload

    return _wa_text_payload(user_id, text_from_guided(guided))




def _reservation_card_payload(user_id: str, message: str) -> Optional[Dict[str, Any]]:
    data = parse_reservation_message(message)
    if not data.get('reservation_id'):
        return None
    body = format_reservation_card(data)
    buttons = [
        {"type": "reply", "reply": {"id": "pay", "title": "Pay now"}},
        {"type": "reply", "reply": {"id": "status", "title": "Check status"}},
        {"type": "reply", "reply": {"id": "reset", "title": "Start over"}},
    ]
    return _wa_button_payload(user_id, body, buttons)


def _seatmap_caption(expect: dict, available: list[str], best: list[str]) -> str:
    pax = int(expect.get("pax") or 1)
    seat_word = "seat" if pax == 1 else "seats"
    number_word = "number" if pax == 1 else "numbers"
    caption_parts = [
        f"I've got {pax} ticket(s) for you.",
        f"Please choose {pax} {seat_word}.",
    ]
    if best:
        caption_parts.append("Best seats: " + ", ".join(best[:4]))
    example = best[0] if best else (available[0] if available else "3")
    caption_parts.append(f"Reply with your seat {number_word}, for example: {example}")
    return "\n".join(caption_parts)


async def build_whatsapp_payloads_from_guided(
    guided: Any,
    user_id: str,
    *,
    text_from_guided: Callable[[Any], str],
    extract_available_seats: Callable[[Any], list[str]],
    recommended_seats: Callable[[Any, list[str]], list[str]],
    seatmap_image_file: Callable[[Any, str], Any],
    upload_media: Callable[[Any], Awaitable[Optional[str]]],
    image_payload_factory: Callable[[str, str, str], Dict[str, Any]],
) -> list[Dict[str, Any]]:
    expect = getattr(guided, "expect", None) or {}
    if isinstance(expect, dict) and expect.get("type") == "passenger_flow":
        body = str(getattr(guided, "message", "") or "Almost done — please fill in the passenger details form.").strip() or "Almost done — please fill in the passenger details form."
        payload = _passenger_flow_payload(user_id, body)
        if payload is not None:
            return [payload]
    if isinstance(expect, dict) and expect.get("type") == "seatmap":
        seats_raw = expect.get("seats")
        available = extract_available_seats(seats_raw)
        best = recommended_seats(seats_raw, list(available))
        caption = _seatmap_caption(expect, available, best)
        image_path = seatmap_image_file(seats_raw, caption)
        if image_path:
            media_id = await upload_media(image_path)
            try:
                image_path.unlink(missing_ok=True)
            except Exception:
                pass
            if media_id:
                return [image_payload_factory(user_id, media_id, caption)]
    return [build_whatsapp_payload_from_guided(guided, user_id, text_from_guided=text_from_guided)]
