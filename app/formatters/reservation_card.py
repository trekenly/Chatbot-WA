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
def _clean(value: Any) -> str:
    return str(value or "").strip()
def _fmt_day(dt: datetime) -> str:
    return f"{dt.day} {dt.strftime('%b %Y • %H:%M')}"
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
def format_reservation_card(data: Dict[str, Any]) -> str:
    departure_en, departure_th = _split_place(data.get("departure") or data.get("from_city") or data.get("depart_station_en"))
    destination_en, destination_th = _split_place(data.get("destination") or data.get("to_city") or data.get("arrive_station_en"))
    seats = _clean(data.get("seats") or data.get("seat"))
    amount = _clean(data.get("amount") or data.get("price"))
    reservation_id = _clean(data.get("reservation_id"))
    order_ref_id = _clean(data.get("order_ref_id") or data.get("order_ref"))
    expires = _fmt_expiry(_clean(data.get("expires_at")))
    name = _clean(data.get("passenger_name") or data.get("name") or data.get("contact_name"))
    email = _clean(data.get("passenger_email") or data.get("email") or data.get("contact_email"))
    phone = _clean(data.get("passenger_phone") or data.get("phone") or data.get("contact_phone_number"))
    route_en = " → ".join([p for p in [departure_en, destination_en] if p])
    route_th = " → ".join([p for p in [departure_th, destination_th] if p])
    lines = ["✅ Reservation Created"]
    if route_en:
        lines += ["", f"🚌 {route_en}"]
    if route_th:
        lines.append(route_th)
    if amount:
        lines.append(f"💵 Total: {amount}")
    if seats:
        lines.append(f"💺 Seat: {seats}")
    if reservation_id:
        lines.append(f"🆔 Booking ID: {reservation_id}")
    if order_ref_id:
        lines.append(f"🔖 Order Ref: {order_ref_id}")
    if expires:
        lines.append(f"⏳ Pay By: {expires}")
    if name or email or phone:
        lines += ["", "👤 Passenger"]
        if name:
            lines.append(f"   {name}")
        if email:
            lines.append(f"   {email}")
        if phone:
            lines.append(f"   {phone}")
    lines += ["", "Tap Pay now to complete your booking."]
    return "\n".join(lines)
def format_reservation_confirm_card(data: Dict[str, Any]) -> str:
    departure_en, departure_th = _split_place(data.get("departure") or data.get("from_city") or data.get("depart_station_en") or data.get("from_label"))
    destination_en, destination_th = _split_place(data.get("destination") or data.get("to_city") or data.get("arrive_station_en") or data.get("to_label"))
    seats = _clean(data.get("seats") or data.get("seat"))
    tickets = _clean(data.get("tickets") or data.get("pax"))
    travel_date = _clean(data.get("departure_date") or data.get("date"))
    name = _clean(data.get("contact_name") or data.get("name"))
    email = _clean(data.get("contact_email") or data.get("email"))
    telephone = _clean(data.get("contact_phone_number") or data.get("telephone") or data.get("phone"))
    route_en = " → ".join([p for p in [departure_en, destination_en] if p])
    route_th = " → ".join([p for p in [departure_th, destination_th] if p])
    lines = ["📝 Please Confirm Your Reservation"]
    if route_en:
        lines += ["", f"🚌 {route_en}"]
    if route_th:
        lines.append(route_th)
    if travel_date:
        lines.append(f"📅 Date: {travel_date}")
    if tickets:
        lines.append(f"🎟 Tickets: {tickets}")
    if seats:
        lines.append(f"💺 Seats: {seats}")
    if departure_en or departure_th:
        lines += ["", "Depart"]
        if departure_en:
            lines.append(departure_en)
        if departure_th:
            lines.append(departure_th)
    if destination_en or destination_th:
        lines += ["", "Arrive"]
        if destination_en:
            lines.append(destination_en)
        if destination_th:
            lines.append(destination_th)
    if name or email or telephone:
        lines += ["", "Passenger"]
        if name:
            lines.append(name)
        if email:
            lines.append(email)
        if telephone:
            lines.append(telephone)
    lines += ["", "Tap Confirm to create the reservation, or Start over to begin again."]
    return "\n".join(lines)
