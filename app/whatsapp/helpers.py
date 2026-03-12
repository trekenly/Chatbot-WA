from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional, Callable

import httpx


def parse_whatsapp_flow_reply(msg: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        if str(msg.get("type") or "") != "interactive":
            return None
        inter = msg.get("interactive") or {}
        if str(inter.get("type") or "") != "nfm_reply":
            return None
        data = inter.get("nfm_reply") or {}
        raw = data.get("response_json")
        if isinstance(raw, str):
            raw = raw.strip()
            flow_data = json.loads(raw) if raw else {}
        elif isinstance(raw, dict):
            flow_data = raw
        else:
            flow_data = {}
        if not isinstance(flow_data, dict):
            return None
        return {
            "first_name": str(flow_data.get("first_name") or flow_data.get("first") or flow_data.get("firstname") or "").strip(),
            "last_name": str(flow_data.get("last_name") or flow_data.get("last") or flow_data.get("lastname") or "").strip(),
            "email": str(flow_data.get("email") or flow_data.get("contact_email") or "").strip(),
            "phone": str(flow_data.get("phone") or flow_data.get("phone_number") or flow_data.get("contact_phone") or "").strip(),
        }
    except Exception:
        return None


def parse_whatsapp_inbound(body: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    try:
        entry = body["entry"][0]
        change = entry["changes"][0]
        value = change["value"]
        msg = value["messages"][0]
        phone = str(msg["from"])
        msg_type = msg.get("type")
        msg_id = str(msg.get("id") or "")
        if msg_type == "text":
            text = msg["text"]["body"]
            return {"user_id": phone, "text": text, "msg_id": msg_id}
        if msg_type == "interactive":
            flow_data = parse_whatsapp_flow_reply(msg)
            if flow_data is not None:
                return {"user_id": phone, "text": json.dumps(flow_data, ensure_ascii=False), "flow_data": flow_data, "msg_id": msg_id}
            inter = msg["interactive"]
            if inter.get("type") == "button_reply":
                text = inter["button_reply"]["id"]
            elif inter.get("type") == "list_reply":
                text = inter["list_reply"]["id"]
            else:
                return None
            return {"user_id": phone, "text": text, "msg_id": msg_id}
        return None
    except Exception:
        return None


def whatsapp_text_from_guided(
    guided: Any,
    extract_available_seats: Callable[[Any], list[str]],
    recommended_seats: Callable[[Any, list[str]], list[str]],
) -> str:
    message = str(getattr(guided, "message", "") or "").strip()
    menu = getattr(guided, "menu", None) or []
    expect = getattr(guided, "expect", None) or {}
    if menu:
        lines = [message] if message else []
        for item in menu:
            idx = str(item.get("i") or "")
            label = str(item.get("label") or idx)
            desc = str(item.get("description") or "").strip()
            lines.append(f"{idx}. {label}" + (f" — {desc}" if desc else ""))
        lines.append("\nReply with the number of your choice.")
        return "\n".join(lines)
    if isinstance(expect, dict) and expect.get("type") == "seatmap":
        seats = extract_available_seats(expect.get("seats"))
        if seats:
            preview = ", ".join(seats[:30])
            more = f" (+{len(seats)-30} more)" if len(seats) > 30 else ""
            best = ", ".join(recommended_seats(expect.get("seats"), seats)[:4])
            extra = f"\nRecommended seats: {best}" if best else ""
            return (message + "\n\n" if message else "") + f"Available seats: {preview}{more}{extra}\n\nReply with your seat number."
    return message or "OK"


def make_wa_upload_media(access_token: str, phone_number_id: str, api_version: str):
    async def _wa_upload_media(image_path: Path) -> Optional[str]:
        if not access_token or not phone_number_id or not image_path or not image_path.exists():
            return None
        url = f"https://graph.facebook.com/{api_version}/{phone_number_id}/media"
        headers = {"Authorization": f"Bearer {access_token}"}
        data = {"messaging_product": "whatsapp", "type": "image/png"}
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                with image_path.open("rb") as fh:
                    files = {"file": (image_path.name, fh, "image/png")}
                    r = await client.post(url, headers=headers, data=data, files=files)
            if r.status_code >= 400:
                print(f"WhatsApp media upload failed status={r.status_code} body={r.text}")
                return None
            media_id = (r.json() or {}).get("id")
            return str(media_id) if media_id else None
        except Exception as exc:
            print(f"WhatsApp media upload exception: {exc}")
            return None

    return _wa_upload_media


def wa_image_payload(user_id: str, media_id: str, caption: str) -> Dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": user_id,
        "type": "image",
        "image": {"id": media_id, "caption": caption[:1024]},
    }
