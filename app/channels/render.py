"""Channel rendering layer — WhatsApp-optimised.

WhatsApp design principles applied here:
  1. Seat map: ASCII bus grid (row × col), bold seat-number for available,
     ⬛ for taken, │ aisle divider between col 2 and col 3.
     Clean available-seats summary + reply instruction at the bottom.
  2. Choices: interactive buttons for ≤ 3 options; interactive list for
     4-10 — title gets time+price (most scannable), description uses all
     72 chars for carrier, boarding point, seats left.
     Plain numbered text only for > 10 options (with descriptions inlined).
  3. Well-known field prompts (date, pax, confirm) always get buttons.

Nothing in this module knows about bookings, NLP, or orchestrator state.
It only reads: envelope.say, envelope.ask, envelope.actions.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Tuple

from app.core.contracts import Ask, AskOption, ChatEnvelope


# ─────────────────────────────────────────────────────────────────────────────
# Utilities
# ─────────────────────────────────────────────────────────────────────────────

def _trunc(text: str, n: int) -> str:
    t = str(text or "").strip()
    return t if len(t) <= n else t[: n - 1] + "…"


def _fmt_month_day(dt: datetime) -> str:
    return f"{dt.strftime('%b')} {dt.day}"

def _date_buttons() -> List[Dict[str, str]]:
    now = datetime.utcnow() + timedelta(hours=7)   # Bangkok time
    t   = _fmt_month_day(now)
    t1  = _fmt_month_day(now + timedelta(days=1))
    return [
        {"id": now.strftime("%Y-%m-%d"),                    "title": f"Today ({t})"},
        {"id": (now + timedelta(days=1)).strftime("%Y-%m-%d"), "title": f"Tomorrow ({t1})"},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Seat-map rendering
# ─────────────────────────────────────────────────────────────────────────────

def _parse_grid(ask: Ask) -> Tuple[List[Tuple[int, int, str, bool]], List[str]]:
    """Parse seat data into (grid_cells, available_labels).
    grid_cells: (row, col, label, is_available)
    """
    raw = ask.seats
    cells: List[Tuple[int, int, str, bool]] = []

    if isinstance(raw, dict):
        for cell in raw.get("seat_layout_details") or []:
            if not isinstance(cell, dict):
                continue
            if str(cell.get("object_code") or "").lower() != "seat":
                continue
            s = cell.get("object_code_seat") or {}
            label = str(s.get("seat_number") or "").strip()
            if not label:
                continue
            status = str(s.get("seat_status") or "").lower()
            avail  = status in {"1", "available", "open"}
            row = s.get("seat_row")    or cell.get("row")    or cell.get("pos_y") or 0
            col = s.get("seat_column") or s.get("seat_col") or cell.get("column") or cell.get("pos_x") or 0
            try: row = int(row)
            except Exception: row = 0
            try: col = int(col)
            except Exception: col = 0
            cells.append((row, col, label, avail))

        if not cells:
            for floor in raw.get("floor_details") or []:
                for row_data in floor.get("seat_layout_details") or []:
                    for cell in (row_data if isinstance(row_data, list) else [row_data]):
                        if not isinstance(cell, dict):
                            continue
                        s = cell.get("object_code_seat") or cell
                        label = str(s.get("seat_number") or s.get("label") or "").strip()
                        if not label:
                            continue
                        status = str(s.get("seat_status") or "").lower()
                        cells.append((0, 0, label, status in {"1", "available", "open"}))

    elif isinstance(raw, list):
        cells = [(0, 0, str(s).strip(), True) for s in raw if str(s).strip()]

    available = [lbl for _, _, lbl, a in cells if a]
    return cells, available


def _seatmap_text(ask: Ask) -> str:
    """Render a compact, readable seat-map message for WhatsApp.

    If we have row/col coordinates → ASCII bus grid with aisle divider.
    Otherwise → 4-column list of available seats.
    Always appends available-seats summary + reply instruction.
    """
    cells, available = _parse_grid(ask)
    pax      = int(ask.pax or 1)
    selected = list(ask.selected or [])

    header = ask.prompt or "Choose your seat"
    lines: List[str] = [f"*{header}*"]

    has_coords = any(r or c for r, c, _, _ in cells)

    if has_coords and cells:
        # Build grid: rows_dict[row][col] = (label, avail)
        rows_dict: Dict[int, Dict[int, Tuple[str, bool]]] = {}
        for r, c, lbl, a in cells:
            rows_dict.setdefault(r, {})[c] = (lbl, a)

        all_cols = sorted({c for _, c, _, _ in cells})
        aisle_after = len(all_cols) // 2   # insert │ after this many cols

        lines.append("")
        for row_idx in sorted(rows_dict):
            row_cells = rows_dict[row_idx]
            parts: List[str] = []
            for i, col_idx in enumerate(all_cols):
                if i == aisle_after:
                    parts.append("│")
                entry = row_cells.get(col_idx)
                if entry is None:
                    parts.append("    ")
                else:
                    lbl, a = entry
                    # Bold available seats (WA markdown), ⬛ for taken
                    parts.append(f"*{lbl:>3}*" if a else "  ⬛")
            lines.append("  " + " ".join(parts))

        lines.append("")
        lines.append("_Bold = available   ⬛ = taken_")

    else:
        # Fallback: 4-per-row compact list
        lines.append("")
        sliced = available[:40]
        for i in range(0, len(sliced), 4):
            row = sliced[i: i + 4]
            left  = "   ".join(f"*{s}*" for s in row[:2])
            right = "   ".join(f"*{s}*" for s in row[2:])
            lines.append(f"  {left}   {right}" if right else f"  {left}")
        if len(available) > 40:
            lines.append(f"  … and {len(available) - 40} more")

    # ── Summary + instruction ────────────────────────────────────────────────
    lines.append("")
    if selected:
        lines.append(f"Already selected: {', '.join(selected)}")

    preview = ", ".join(available[:20])
    extra   = f" (+{len(available) - 20} more)" if len(available) > 20 else ""
    lines.append(f"✅ Available ({len(available)} seats): {preview}{extra}")
    lines.append("")

    ex = ",".join(available[:pax]) if len(available) >= pax else ("12,13" if pax > 1 else "12")
    if pax == 1:
        lines.append(f"Reply with 1 seat number — e.g. *{ex}*")
    else:
        lines.append(f"Reply with {pax} seat numbers separated by commas — e.g. *{ex}*")

    return "\n".join(lines)


# ─────────────────────────────────────────────────────────────────────────────
# Trip-option label splitting for WA list (title ≤24, description ≤72)
# ─────────────────────────────────────────────────────────────────────────────

_PIPE_RE = re.compile(r"\s*\|\s*")


def _split_trip_label(label: str, desc: str) -> Tuple[str, str]:
    """Split a trip label string into (wa_title ≤24, wa_description ≤72).

    Input label format (from format_trip_option):
      "08:00 → 14:30 | Sombat Tour VIP | 350.00 THB per ticket | 8 seat(s) left"
    Input desc (from _trip_help_line):
      "Board at Mochit Terminal | Arrive at Phuket Bus Terminal"
    """
    parts = _PIPE_RE.split(label)
    time_part    = parts[0].strip() if parts else ""
    carrier_part = parts[1].strip() if len(parts) > 1 else ""
    price_part   = parts[2].strip() if len(parts) > 2 else ""
    seats_part   = parts[3].strip() if len(parts) > 3 else ""

    # Compact price
    price_short = ""
    pm = re.search(r"([\d,]+\.?\d*)\s*([A-Z]{3})", price_part)
    if pm:
        price_short = f"฿{pm.group(1)}" if pm.group(2) == "THB" else f"{pm.group(1)} {pm.group(2)}"

    # Compact seats
    seats_short = ""
    sm = re.search(r"(\d+)\s*seat", seats_part)
    if sm:
        seats_short = f"🪑 {sm.group(1)} seats"

    # WA title: times + price
    raw_title = f"{time_part}  {price_short}".strip() if price_short else time_part
    wa_title  = _trunc(raw_title, 24)

    # WA description: carrier • boarding point • seats left
    desc_bits = []
    if carrier_part:
        desc_bits.append(carrier_part)
    if desc:
        bm = re.search(r"Board(?:ing)? at ([^|]+)", desc, re.IGNORECASE)
        if bm:
            desc_bits.append(f"📍 {bm.group(1).strip()}")
    if seats_short:
        desc_bits.append(seats_short)
    wa_desc = _trunc("  •  ".join(desc_bits), 72)

    return wa_title, wa_desc


def _enrich_options(options: List[AskOption]) -> List[AskOption]:
    """Re-pack trip options with WhatsApp-optimal title/description."""
    result: List[AskOption] = []
    for opt in options:
        if re.search(r"\d{2}:\d{2}\s*[→>-]\s*\d{2}:\d{2}", opt.label or ""):
            title, desc = _split_trip_label(opt.label, opt.description or "")
            result.append(AskOption(value=opt.value, label=title, description=desc))
        else:
            result.append(opt)
    return result


# ─────────────────────────────────────────────────────────────────────────────
# WA payload builders
# ─────────────────────────────────────────────────────────────────────────────

def _wa_text(wa_to: str, body: str) -> Dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": wa_to,
        "type": "text",
        "text": {"body": body[:4096]},
    }


def _wa_buttons(wa_to: str, body: str, buttons: List[Dict[str, str]]) -> Dict[str, Any]:
    return {
        "messaging_product": "whatsapp",
        "to": wa_to,
        "type": "interactive",
        "interactive": {
            "type": "button",
            "body": {"text": body[:1024]},
            "action": {
                "buttons": [
                    {"type": "reply", "reply": {"id": b["id"], "title": _trunc(b["title"], 20)}}
                    for b in buttons[:3]
                ]
            },
        },
    }


def _infer_list_context(say: str, opts: List[AskOption]) -> Tuple[str, str]:
    """Infer (button_text, section_title) from the prompt and options.

    Reads the say/prompt text to produce a label that matches exactly what
    the user sees in the screenshot — Destinations, Departures, Trips, etc.
    """
    low = (say or "").lower()
    is_trips = any(re.search(r"\d{2}:\d{2}", o.label) for o in opts)

    if is_trips:
        return "View trips", "Available trips"
    if any(w in low for w in ("depart", "going from", "which city are you", "where are you departing")):
        return "Departures", "Departure cities"
    if any(w in low for w in ("destination", "going to", "where are you going", "arrive")):
        return "Destinations", "Destination cities"
    if "terminal" in low:
        return "Terminals", "Bus terminals"
    if "operator" in low or "company" in low or "carrier" in low:
        return "Operators", "Bus operators"
    if "class" in low or "cabin" in low or "type" in low:
        return "Ticket types", "Options"
    # Generic fallback
    return "Choose", "Options"


def _wa_list(
    wa_to: str,
    body: str,
    options: List[AskOption],
    button_text: str = "Choose",
    section_title: str = "Options",
) -> Dict[str, Any]:
    """Interactive list — supports up to 10 sections × 10 rows = 100 items.

    If options > 10, they are chunked into labelled sections automatically.
    """
    # Chunk into groups of 10 (WA limit per section)
    chunks: List[List[AskOption]] = []
    for i in range(0, min(len(options), 100), 10):
        chunks.append(options[i: i + 10])

    sections = []
    for idx, chunk in enumerate(chunks):
        # For multi-section lists label each range; single section uses the title as-is
        if len(chunks) > 1:
            start = idx * 10 + 1
            end   = start + len(chunk) - 1
            s_title = f"{section_title} {start}–{end}"
        else:
            s_title = section_title

        rows = []
        for opt in chunk:
            row: Dict[str, Any] = {"id": _trunc(opt.value, 200), "title": _trunc(opt.label, 24)}
            desc = (opt.description or "").strip()
            if desc:
                row["description"] = _trunc(desc, 72)
            rows.append(row)
        sections.append({"title": _trunc(s_title, 24), "rows": rows})

    return {
        "messaging_product": "whatsapp",
        "to": wa_to,
        "type": "interactive",
        "interactive": {
            "type": "list",
            "body": {"text": body[:1024]},
            "action": {
                "button": _trunc(button_text, 20),
                "sections": sections,
            },
        },
    }


# Patterns that encourage typing — removed from all WA messages so users tap, not type.
_TYPE_HINT_RE = re.compile(
    r"(?im)"
    r"("
    r"(or\s+)?type\s+(something\s+like|a\s+(city|number|date|terminal)|another\s+\w+|the\s+\w+)[^\n]*"
    r"|you\s+can\s+(also\s+)?type\s+[^\n]+"
    r"|or\s+type\s+[^\n]+"
    r"|reply\s+with\s+(a\s+)?(number|the\s+number)\s+[^\n]+"
    r")"
    r"\n?"
)

def _strip_type_hints(text: str) -> str:
    """Remove 'You can type…', 'Or type…', 'Reply with a number…' lines."""
    cleaned = _TYPE_HINT_RE.sub("", text or "")
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned.strip()


def _numbered_list(prompt: str, options: List[AskOption]) -> str:
    """Fallback for > 100 options — numbered text with descriptions inlined."""
    lines = [_strip_type_hints(prompt)] if prompt else []
    for i, opt in enumerate(options, 1):
        desc_part = f"\n   _{opt.description}_" if (opt.description or "").strip() else ""
        lines.append(f"{i}. *{opt.label}*{desc_part}")
    lines.append("\nTap a number to choose.")
    return "\n".join(lines)



# ─────────────────────────────────────────────────────────────────────────────
# Web
# ─────────────────────────────────────────────────────────────────────────────

def render_web(env: ChatEnvelope) -> Dict[str, Any]:
    """Pass the full envelope through — React frontend handles rendering."""
    return env.model_dump()


# ─────────────────────────────────────────────────────────────────────────────
# WhatsApp (Meta Cloud API)
# ─────────────────────────────────────────────────────────────────────────────

def render_whatsapp(env: ChatEnvelope, wa_to: str) -> Dict[str, Any]:
    """Build a WhatsApp Cloud API payload optimised for mobile readability."""
    ask = env.ask
    # Strip all "You can type..." / "Or type..." nudges — users tap, not type.
    say = _strip_type_hints(env.say or (ask.prompt if ask else "") or "")

    # ── 1. Seat map → ASCII grid ─────────────────────────────────────────────
    if ask and ask.type == "seatmap":
        return _wa_text(wa_to, _seatmap_text(ask))

    # ── 2. Well-known field prompts → buttons ────────────────────────────────
    if ask and ask.type == "field":
        field = (ask.field or "").strip().lower()
        prompt = _strip_type_hints(ask.prompt or say or "")
        low = prompt.lower()

        if field in {"departure_date", "date", "travel_date"} or "date" in low:
            return _wa_buttons(wa_to, prompt, _date_buttons())

        if field in {"pax", "tickets", "ticket_count", "passengers"} or "how many" in low:
            return _wa_buttons(
                wa_to, prompt,
                [{"id": "1", "title": "1 ticket"},
                 {"id": "2", "title": "2 tickets"},
                 {"id": "3", "title": "3 tickets"}],
            )

        if field in {"confirm", "confirm_reservation", "confirmation"} or \
                "confirm" in low or "reply yes" in low:
            return _wa_buttons(
                wa_to, prompt,
                [{"id": "yes",   "title": "✅ Confirm"},
                 {"id": "reset", "title": "✖ Start over"}],
            )

    # ── 3. Choice ────────────────────────────────────────────────────────────
    if ask and ask.type == "choice" and ask.options:
        opts = _enrich_options(ask.options)
        n = len(opts)

        if n <= 3:
            buttons = [{"id": o.value, "title": _trunc(o.label, 20)} for o in opts]
            body = say
            desc_lines = [
                f"*{o.label}*\n_{o.description}_"
                for o in opts if (o.description or "").strip()
            ]
            if desc_lines:
                body = say + "\n\n" + "\n\n".join(desc_lines)
            return _wa_buttons(wa_to, body, buttons)

        # 4-100 options: interactive list with context-aware labels
        if n <= 100:
            btn_text, sec_title = _infer_list_context(say, opts)
            return _wa_list(wa_to, say, opts,
                            button_text=btn_text, section_title=sec_title)


    # ── 4. Plain text ────────────────────────────────────────────────────────
    return _wa_text(wa_to, say)


def parse_whatsapp_inbound(body: Dict[str, Any]) -> Optional[Dict[str, str]]:
    """Extract (user_phone, text) from a WhatsApp Cloud API webhook payload."""
    try:
        msg   = body["entry"][0]["changes"][0]["value"]["messages"][0]
        phone = str(msg["from"])
        mtype = msg.get("type")
        if mtype == "text":
            text = msg["text"]["body"]
        elif mtype == "interactive":
            inter = msg["interactive"]
            if inter["type"] == "button_reply":
                text = inter["button_reply"]["id"]
            elif inter["type"] == "list_reply":
                text = inter["list_reply"]["id"]
            else:
                return None
        else:
            return None
        return {"user_id": phone, "text": text, "channel": "whatsapp"}
    except (KeyError, IndexError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# LINE (Messaging API)
# ─────────────────────────────────────────────────────────────────────────────

def render_line(env: ChatEnvelope, reply_token: str) -> Dict[str, Any]:
    ask = env.ask

    if ask and ask.type == "choice" and ask.options:
        if len(ask.options) <= 13:
            return {
                "replyToken": reply_token,
                "messages": [{
                    "type": "text",
                    "text": env.say,
                    "quickReply": {
                        "items": [
                            {"type": "action", "action": {
                                "type": "message",
                                "label": _trunc(o.label, 20),
                                "text": o.value,
                            }}
                            for o in ask.options[:13]
                        ]
                    },
                }],
            }
        return {
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": _numbered_list(env.say, ask.options)}],
        }

    if ask and ask.type == "seatmap":
        return {
            "replyToken": reply_token,
            "messages": [{"type": "text", "text": _seatmap_text(ask)}],
        }

    return {
        "replyToken": reply_token,
        "messages": [{"type": "text", "text": env.say}],
    }


def parse_line_inbound(body: Dict[str, Any]) -> Optional[Dict[str, str]]:
    try:
        event = body["events"][0]
        if event.get("type") != "message":
            return None
        msg = event.get("message", {})
        if msg.get("type") != "text":
            return None
        return {
            "user_id": event["source"]["userId"],
            "text": msg["text"],
            "reply_token": event["replyToken"],
            "channel": "line",
        }
    except (KeyError, IndexError, TypeError):
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Facebook Messenger (Graph API)
# ─────────────────────────────────────────────────────────────────────────────

def render_messenger(env: ChatEnvelope, recipient_id: str) -> Dict[str, Any]:
    ask = env.ask

    if ask and ask.type == "choice" and ask.options:
        if len(ask.options) <= 13:
            return {
                "recipient": {"id": recipient_id},
                "message": {
                    "text": env.say,
                    "quick_replies": [
                        {"content_type": "text",
                         "title": _trunc(o.label, 20),
                         "payload": o.value}
                        for o in ask.options[:13]
                    ],
                },
            }
        return {
            "recipient": {"id": recipient_id},
            "message": {"text": _numbered_list(env.say, ask.options)},
        }

    if ask and ask.type == "seatmap":
        return {
            "recipient": {"id": recipient_id},
            "message": {"text": _seatmap_text(ask)},
        }

    return {
        "recipient": {"id": recipient_id},
        "message": {"text": env.say},
    }


def parse_messenger_inbound(body: Dict[str, Any]) -> Optional[Dict[str, str]]:
    try:
        messaging = body["entry"][0]["messaging"][0]
        sender_id = messaging["sender"]["id"]
        msg  = messaging.get("message", {})
        text = msg.get("text")
        qr   = msg.get("quick_reply")
        if qr:
            text = qr.get("payload") or text
        if not text:
            return None
        return {"user_id": sender_id, "text": str(text), "channel": "messenger"}
    except (KeyError, IndexError, TypeError):
        return None
