from __future__ import annotations
from datetime import datetime
from typing import Any, Dict

CITY_THAI = {
    "Bangkok": "กรุงเทพฯ",
    "Phuket": "ภูเก็ต",
    "Krabi": "กระบี่",
    "Chiang Mai": "เชียงใหม่",
    "Pattaya": "พัทยา",
    "Hua Hin": "หัวหิน",
    "Surat Thani": "สุราษฎร์ธานี",
}
PLACE_INFO = {
    "Bangkok Bus Terminal Southern (Sai Tai Mai)": ("Sai Tai Mai", "สายใต้ใหม่"),
    "Sai Tai Mai": ("Sai Tai Mai", "สายใต้ใหม่"),
    "Bangkok Bus Terminal Chatuchak (Mo Chit 2)": ("Mo Chit 2", "หมอชิต 2"),
    "Mo Chit 2": ("Mo Chit 2", "หมอชิต 2"),
    "Bangkok Bus Terminal (Ekkamai)": ("Ekkamai", "เอกมัย"),
    "Bangkok Bus Terminal Eastern (Ekkamai)": ("Ekkamai", "เอกมัย"),
    "Ekkamai": ("Ekkamai", "เอกมัย"),
    "Phuket Bus Terminal 2": ("Phuket Bus Terminal 2", "สถานีขนส่งภูเก็ต แห่งที่ 2"),
    "Phuket Bus Terminal 1": ("Phuket Bus Terminal 1", "สถานีขนส่งภูเก็ต แห่งที่ 1"),
    "Krabi Bus Terminal": ("Krabi Bus Terminal", "สถานีขนส่งกระบี่"),
}

_DIV = "─────────────────"


def _clean(value: Any) -> str:
    return str(value or "").strip()


def _fmt_day(dt: datetime) -> str:
    return f"{dt.day} {dt.strftime('%b %Y')}  •  {dt.strftime('%H:%M')}"


def _fmt_expiry(value: str) -> str:
    raw = _clean(value)
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        return _fmt_day(dt)
    except Exception:
        try:
            dt = datetime.fromisoformat(raw.split(".")[0])
            return _fmt_day(dt)
        except Exception:
            return raw


def _fmt_amount(total_price: str, currency: str) -> str:
    raw = _clean(total_price)
    if not raw:
        return ""
    cur = _clean(currency).upper() or "THB"
    # Format number with thousands separator
    try:
        num = float(raw.replace(",", ""))
        formatted = f"{num:,.2f}"
    except ValueError:
        formatted = raw
    if cur == "THB":
        return f"฿{formatted}"
    return f"{formatted} {cur}"


def _split_place(raw: str) -> tuple[str, str]:
    text = _clean(raw)
    if not text:
        return "", ""
    text = text.split("—", 1)[0].strip()
    if text in PLACE_INFO:
        return PLACE_INFO[text]
    if text in CITY_THAI:
        return text, CITY_THAI[text]
    return text, ""


def parse_reservation_message(text: str) -> Dict[str, str]:
    data: Dict[str, str] = {}
    for raw_line in str(text or "").splitlines():
        line = raw_line.strip()
        if not line:
            continue
        low = line.lower()
        if low.startswith("seats held:"):
            data["seats"] = line.split(":", 1)[1].strip()
            continue
        if low.startswith("✅ reservation created"):
            data["status"] = "created"
            continue
        if ":" in line:
            key, value = line.split(":", 1)
            data[key.strip().lower().replace(" ", "_")] = value.strip()
    return data


def _route_lines(data: Dict[str, Any]) -> list[str]:
    """Return 1-2 route lines with locale-aware primary and 🛺 Thai subtitle."""
    locale = _clean(data.get("locale") or "").lower()[:2]   # "th", "en", "zh" …

    canonical = (
        data.get("departure") or data.get("from_label") or
        data.get("from_city") or data.get("depart_station_en") or ""
    )
    canonical_en, canonical_th = _split_place(canonical)

    canonical_dest = (
        data.get("destination") or data.get("to_label") or
        data.get("to_city") or data.get("arrive_station_en") or ""
    )
    dest_en, dest_th = _split_place(canonical_dest)

    # User-language labels (what the user actually typed / session resolved)
    user_from = _clean(data.get("desired_from_text") or "")
    user_to   = _clean(data.get("desired_to_text") or "")

    # Build en / th route strings
    route_en = "  →  ".join(p for p in [canonical_en, dest_en] if p)
    route_th = "  →  ".join(p for p in [canonical_th, dest_th] if p)

    # For non-English/non-Thai locales use what the user typed as the primary label
    route_user = ""
    if locale not in {"en", "th", ""} and (user_from or user_to):
        route_user = "  →  ".join(p for p in [user_from, user_to] if p)

    out: list[str] = []
    if locale == "th":
        # Thai first with 🛺, English subtitle
        if route_th:
            out.append(f"🛺 *{route_th}*")
        if route_en:
            out.append(f"   _{route_en}_")
    elif route_user:
        # Other language: user's own text first, then Thai with 🛺
        out.append(f"🚌 *{route_user}*")
        if route_th:
            out.append(f"   🛺 _{route_th}_")
    else:
        # English default: English first, Thai with 🛺 subtitle
        if route_en:
            out.append(f"🚌 *{route_en}*")
        if route_th:
            out.append(f"   🛺 _{route_th}_")
    return out


def format_reservation_card(data: Dict[str, Any]) -> str:
    """Render a polished WhatsApp booking-confirmed card."""
    seats       = _clean(data.get("seats") or data.get("seat"))
    amount      = _fmt_amount(
        data.get("total_price") or data.get("amount") or data.get("price") or "",
        data.get("currency") or "THB",
    )
    travel_date = _clean(data.get("departure_date") or data.get("travel_date") or data.get("date"))
    reservation_id = _clean(data.get("reservation_id") or data.get("booking_id"))
    order_ref_id   = _clean(data.get("order_ref_id") or data.get("order_ref"))
    expires        = _fmt_expiry(_clean(data.get("expires_at")))
    name  = _clean(data.get("passenger_name") or data.get("name") or data.get("contact_name"))
    email = _clean(data.get("passenger_email") or data.get("email") or data.get("contact_email"))
    phone = _clean(
        data.get("passenger_phone") or data.get("passenger_phone_number") or
        data.get("phone") or data.get("contact_phone_number")
    )

    lines = ["🎉 *Booking Confirmed!*"]

    # Route (locale-aware)
    route = _route_lines(data)
    if route:
        lines += [""] + route

    # Journey details
    lines += ["", _DIV]
    if travel_date:
        lines.append(f"📅  {travel_date}")
    if seats:
        lines.append(f"💺  Seat {seats}")
    if amount:
        lines.append(f"💰  {amount}")
    if expires:
        lines.append(f"⏰  Pay by:  {expires}")
    lines.append(_DIV)

    # Booking reference
    if reservation_id:
        lines += ["", f"🔖  *{reservation_id}*"]
        if order_ref_id:
            lines.append(f"    _{order_ref_id}_")

    # Passenger
    if name or email or phone:
        lines += ["", f"👤  *{name}*" if name else "👤  Passenger"]
        if email:
            lines.append(f"    {email}")
        if phone:
            lines.append(f"    {phone}")

    lines += ["", _DIV]
    return "\n".join(lines)


def format_reservation_confirm_card(data: Dict[str, Any]) -> str:
    """Render a polished WhatsApp pre-confirmation summary card."""
    departure_en, departure_th = _split_place(
        data.get("departure") or data.get("from_label") or
        data.get("from_city") or data.get("depart_station_en") or ""
    )
    destination_en, destination_th = _split_place(
        data.get("destination") or data.get("to_label") or
        data.get("to_city") or data.get("arrive_station_en") or ""
    )

    seats       = _clean(data.get("seats") or data.get("seat"))
    tickets     = _clean(data.get("tickets") or data.get("pax"))
    travel_date = _clean(data.get("departure_date") or data.get("date"))
    name      = _clean(data.get("contact_name") or data.get("name"))
    email     = _clean(data.get("contact_email") or data.get("email"))
    telephone = _clean(
        data.get("contact_phone_number") or data.get("telephone") or data.get("phone")
    )

    lines = ["📋 *Please Confirm Your Booking*"]

    route_en = "  →  ".join(p for p in [departure_en, destination_en] if p)
    if route_en:
        lines += ["", f"🚌 *{route_en}*"]
    route_th = "  →  ".join(p for p in [departure_th, destination_th] if p)
    if route_th:
        lines.append(f"   _{route_th}_")

    lines += ["", _DIV]
    if travel_date:
        lines.append(f"📅  {travel_date}")
    if tickets:
        lines.append(f"🎟  {tickets} ticket{'s' if tickets != '1' else ''}")
    if seats:
        lines.append(f"💺  Seat {seats}")
    lines.append(_DIV)

    if name or email or telephone:
        lines += ["", f"👤  *{name}*" if name else "👤  Passenger"]
        if email:
            lines.append(f"    {email}")
        if telephone:
            lines.append(f"    {telephone}")

    lines += ["", _DIV, "Tap *Confirm* to reserve — or *Start over* to restart."]
    return "\n".join(lines)
