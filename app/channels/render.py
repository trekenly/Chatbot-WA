"""Channel rendering layer — WhatsApp-optimised.

WhatsApp design principles applied here:
  1. Seat map: emoji bus grid — 🟩 available, ⬜ taken, │ aisle, 🚌 driver.
     Row/col from API coordinates if available; inferred from labels (A3 → row 3
     col 1) otherwise.  Clean available-seats summary + reply instruction below.
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


# ─── i18n button labels ───────────────────────────────────────────────────────
# Keys: today, tomorrow, n_tickets(n), confirm, start_over
# WhatsApp button title limit: 20 chars
_I18N: Dict[str, Any] = {
    "th": {
        "today":      "วันนี้",
        "tomorrow":   "พรุ่งนี้",
        "n_tickets":  lambda n: f"{n} ตั๋ว",
        "confirm":    "✅ ยืนยัน",
        "start_over": "✖ เริ่มใหม่",
    },
    "zh": {
        "today":      "今天",
        "tomorrow":   "明天",
        "n_tickets":  lambda n: f"{n} 张票",
        "confirm":    "✅ 确认",
        "start_over": "✖ 重新开始",
    },
    "ko": {
        "today":      "오늘",
        "tomorrow":   "내일",
        "n_tickets":  lambda n: f"티켓 {n}장",
        "confirm":    "✅ 확인",
        "start_over": "✖ 다시 시작",
    },
    "ja": {
        "today":      "今日",
        "tomorrow":   "明日",
        "n_tickets":  lambda n: f"{n} 枚",
        "confirm":    "✅ 確認",
        "start_over": "✖ やり直す",
    },
    "id": {
        "today":      "Hari ini",
        "tomorrow":   "Besok",
        "n_tickets":  lambda n: f"{n} tiket",
        "confirm":    "✅ Konfirmasi",
        "start_over": "✖ Mulai ulang",
    },
    "ms": {
        "today":      "Hari ini",
        "tomorrow":   "Esok",
        "n_tickets":  lambda n: f"{n} tiket",
        "confirm":    "✅ Sahkan",
        "start_over": "✖ Mulai semula",
    },
    "fr": {
        "today":      "Aujourd'hui",
        "tomorrow":   "Demain",
        "n_tickets":  lambda n: f"{n} billet{'s' if n > 1 else ''}",
        "confirm":    "✅ Confirmer",
        "start_over": "✖ Recommencer",
    },
    "es": {
        "today":      "Hoy",
        "tomorrow":   "Mañana",
        "n_tickets":  lambda n: f"{n} boleto{'s' if n > 1 else ''}",
        "confirm":    "✅ Confirmar",
        "start_over": "✖ Reiniciar",
    },
    "ru": {
        "today":      "Сегодня",
        "tomorrow":   "Завтра",
        "n_tickets":  lambda n: f"{n} билет{'а' if n in {2,3,4} else '' if n==1 else 'ов'}",
        "confirm":    "✅ Подтвердить",
        "start_over": "✖ Заново",
    },
    # English default (also covers "en" explicit)
    "en": {
        "today":      "Today",
        "tomorrow":   "Tomorrow",
        "n_tickets":  lambda n: f"{n} ticket{'s' if n > 1 else ''}",
        "confirm":    "✅ Confirm",
        "start_over": "✖ Start over",
    },
}

def _t(locale: str, key: str, *args: Any) -> str:
    """Look up a UI string for the given locale, falling back to English."""
    lang = (locale or "en")[:2].lower()
    strings = _I18N.get(lang) or _I18N["en"]
    val = strings.get(key) or _I18N["en"].get(key, key)
    return val(*args) if callable(val) else str(val)

def _detect_locale_from_text(text: str) -> str:
    """Infer a 2-letter locale from Unicode script present in text."""
    for ch in (text or ""):
        cp = ord(ch)
        if 0x0E00 <= cp <= 0x0E7F:   return "th"   # Thai
        if 0xAC00 <= cp <= 0xD7AF:   return "ko"   # Korean Hangul
        if 0x3040 <= cp <= 0x30FF:   return "ja"   # Japanese kana
        if 0x4E00 <= cp <= 0x9FFF:   return "zh"   # CJK (Chinese/Japanese)
        if 0x0400 <= cp <= 0x04FF:   return "ru"   # Cyrillic
    return "en"


def _date_buttons(locale: str = "en") -> List[Dict[str, str]]:
    now  = datetime.utcnow() + timedelta(hours=7)   # Bangkok time
    tmr  = now + timedelta(days=1)
    d0   = f"{now.day}/{now.month}"
    d1   = f"{tmr.day}/{tmr.month}"
    return [
        {"id": now.strftime("%Y-%m-%d"),
         "title": _trunc(f"{_t(locale, 'today')} ({d0})", 20)},
        {"id": tmr.strftime("%Y-%m-%d"),
         "title": _trunc(f"{_t(locale, 'tomorrow')} ({d1})", 20)},
    ]


# ─────────────────────────────────────────────────────────────────────────────
# Seat-map rendering
# ─────────────────────────────────────────────────────────────────────────────

def _label_to_pos(label: str) -> Optional[Tuple[int, int]]:
    """'A3' → (row=3, col=1),  'B10' → (10, 2).  None if unparseable."""
    m = re.match(r'^([A-Za-z]+)(\d+)', label.strip())
    if not m:
        return None
    col_str, row_str = m.groups()
    col = 0
    for ch in col_str.upper():
        col = col * 26 + (ord(ch) - ord('A') + 1)
    return int(row_str), col


# BusX object_code → internal type
_OBJ_TYPE: Dict[str, str] = {
    "seat":            "seat",
    "driver":          "driver",
    "stair":           "stair",
    "walkway":         "walkway",    # the aisle
    "toilet":          "toilet",
    "empty":           "empty",
    "extra_seat":      "seat",
    "wheel_seat":      "seat",
    "handycapped_seat": "seat",
    "wheel":           "empty",
}

# How each non-seat cell renders in the WhatsApp grid (fixed 4-char wide slot)
_OBJ_GLYPH: Dict[str, str] = {
    "driver":   "🚌  ",
    "stair":    "🪜  ",
    "toilet":   "🚽  ",
    "walkway":  " │  ",    # aisle column — rendered as │
    "empty":    "    ",
}


def _parse_grid(ask: Ask) -> Tuple[
    List[Tuple[int, int, str, str]],   # all_cells: (y, x, label, cell_type)
    List[str],                          # available seat labels
]:
    """Parse BusX seat_layout_details into a full grid + available list.

    Each cell is (row=y, col=x, label, cell_type).
    cell_type: 'available' | 'taken' | 'walkway' | 'driver' | 'stair' | 'toilet' | 'empty'
    Coordinates come directly from API fields y/x (BusX v2).
    """
    raw = ask.seats
    cells: List[Tuple[int, int, str, str]] = []

    def _extract(items: list) -> None:
        for cell in items:
            if not isinstance(cell, dict):
                continue
            obj = str(cell.get("object_code") or "").lower()
            typ = _OBJ_TYPE.get(obj, "empty")

            # API v2 uses y=row, x=col at the top-level cell
            try: r = int(cell.get("y") or cell.get("seat_row") or cell.get("row") or 0)
            except Exception: r = 0
            try: c = int(cell.get("x") or cell.get("seat_col") or cell.get("col") or 0)
            except Exception: c = 0

            if typ == "seat":
                s     = cell.get("object_code_seat") or {}
                lbl   = str(s.get("seat_number") or "").strip()
                if not lbl:
                    continue
                status = str(s.get("seat_status") or "").lower()
                avail  = status in {"1", "available", "open"}
                cells.append((r, c, lbl, "available" if avail else "taken"))
            else:
                cells.append((r, c, "", typ))

    if isinstance(raw, dict):
        flat = raw.get("seat_layout_details") or []
        if flat:
            _extract(flat)
        if not cells:
            for floor in raw.get("floor_details") or []:
                for row_data in floor.get("seat_layout_details") or []:
                    _extract(row_data if isinstance(row_data, list) else [row_data])
    elif isinstance(raw, list):
        # Plain list of seat labels — no coordinates
        cells = [(0, 0, str(s).strip(), "available") for s in raw if str(s).strip()]

    available = [lbl for _, _, lbl, ct in cells if ct == "available"]
    return cells, available


def _seatmap_text(ask: Ask) -> str:
    """Render an emoji bus-grid seat-map for WhatsApp.

    Uses BusX x/y coordinates directly.  walkway columns become │ aisle.
    🟩 open   ⬜ taken   🚌 driver   🪜 stairs   🚽 toilet
    """
    cells, available = _parse_grid(ask)
    pax      = int(ask.pax or 1)
    selected = list(ask.selected or [])

    header = ask.prompt or "Choose your seat"
    lines: List[str] = [f"*{header}*", ""]

    has_coords = any(r or c for r, c, _, _ in cells)

    # ── Infer positions from seat labels when API gives no coordinates ─────
    if not has_coords and cells:
        inferred: List[Tuple[int, int, str, str]] = []
        ok = True
        for _, _, lbl, ct in cells:
            if ct == "available":
                pos = _label_to_pos(lbl)
                if pos is None:
                    ok = False
                    break
                inferred.append((pos[0], pos[1], lbl, ct))
        if ok and inferred:
            cells      = inferred
            has_coords = True

    # ── Full grid (monospace code block for perfect alignment) ───────────
    if has_coords and cells:
        # Build grid dict: grid[row][col] = (label, cell_type)
        grid: Dict[int, Dict[int, Tuple[str, str]]] = {}
        for r, c, lbl, ct in cells:
            grid.setdefault(r, {})[c] = (lbl, ct)

        all_rows = sorted(grid)
        all_cols = sorted({c for r in grid.values() for c in r})

        # Fixed cell width: wide enough for the longest seat label (min 3 for "DRV")
        max_lbl = max(
            (len(lbl) for _, _, lbl, ct in cells if ct in {"available", "taken"} and lbl),
            default=2,
        )
        cw = max(max_lbl, 3)   # chars inside the brackets, e.g. 3 → "[A2 ]" is 5 chars wide

        def _cell(lbl: str, ct: str) -> str:
            """Return a fixed (cw+2)-char wide cell string — pure ASCII, no emoji."""
            pad = (lbl or "")[:cw].ljust(cw)
            if ct == "available":
                return f"[{pad}]"
            if ct == "taken":
                return f"[{'--':^{cw}}]"   # [--] — universally understood as occupied
            if ct == "walkway":
                aisle = "|".center(cw)
                return f" {aisle} "
            if ct == "driver":
                return f"[{'DRV':^{cw}}]"
            if ct == "stair":
                return f"[{'STR':^{cw}}]"
            if ct == "toilet":
                return f"[{'WC':^{cw}}]"
            return " " * (cw + 2)   # empty

        grid_lines: List[str] = []
        for row_idx in all_rows:
            row_data = grid[row_idx]
            parts: List[str] = []
            for col_idx in all_cols:
                lbl, ct = row_data.get(col_idx, ("", "empty"))
                parts.append(_cell(lbl, ct))
            grid_lines.append(" ".join(parts))

        lines.append("```")
        lines.extend(grid_lines)
        lines.append("```")
        lines.append("")
        lines.append("[A3] = open   [--] = taken   [DRV] = driver   [STR] = stairs")

    # ── Fallback: simple emoji list ───────────────────────────────────────
    else:
        avail_set  = set(available)
        all_labels = [lbl for _, _, lbl, ct in cells if ct in {"available", "taken"} and lbl]
        if not all_labels:
            all_labels = available
        for i in range(0, len(all_labels), 4):
            row_lbls = all_labels[i: i + 4]
            parts = [f"🟩{lbl}" if lbl in avail_set else f"⬜{lbl}" for lbl in row_lbls]
            lines.append("  " + "   ".join(parts))
        if not all_labels:
            lines.append("  (no seat data)")
        lines.append("")
        lines.append("🟩 open   ⬜ taken")

    # ── Summary + instruction ─────────────────────────────────────────────────
    lines.append("")
    if selected:
        lines.append(f"Selected: {', '.join(selected)}")

    preview = ", ".join(available[:20])
    extra   = f" (+{len(available) - 20} more)" if len(available) > 20 else ""
    lines.append(f"✅ Available ({len(available)} seats): {preview}{extra}")
    lines.append("")

    ex = ",".join(available[:pax]) if len(available) >= pax else ("A3,B3" if pax > 1 else "A3")
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
            if "|" in (opt.label or ""):
                # Old pipe-separated format — split and reformat
                title, desc = _split_trip_label(opt.label, opt.description or "")
            else:
                # format_trip_option already split label/description correctly — preserve it
                title = _trunc(opt.label or "", 24)
                desc  = _trunc(opt.description or "", 72)
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

    # ── Locale: chat_language (set by pipeline NLP) > session locale > detect ──
    locale: str = (
        env.state.get("chat_language") or   # "th", "zh", "ko" … from Claude NLP
        env.state.get("locale") or          # session locale, usually "en_US"
        ""
    ).strip()[:2].lower() or _detect_locale_from_text(say)

    # ── 1. Seat map → ASCII grid ─────────────────────────────────────────────
    if ask and ask.type == "seatmap":
        return _wa_text(wa_to, _seatmap_text(ask))

    # ── 2. Well-known field prompts → buttons ────────────────────────────────
    if ask and ask.type == "field":
        field = (ask.field or "").strip().lower()
        prompt = _strip_type_hints(ask.prompt or say or "")
        low = prompt.lower()

        if field in {"departure_date", "date", "travel_date"} or "date" in low:
            return _wa_buttons(wa_to, prompt, _date_buttons(locale))

        if field in {"pax", "tickets", "ticket_count", "passengers"} or "how many" in low:
            return _wa_buttons(
                wa_to, prompt,
                [{"id": str(n), "title": _t(locale, "n_tickets", n)} for n in (1, 2, 3)],
            )

        if field in {"confirm", "confirm_reservation", "confirmation"} or \
                "reply yes" in low or \
                re.search(r'\bconfirm\b(?!ation)', low):
            return _wa_buttons(
                wa_to, prompt,
                [{"id": "yes",   "title": _t(locale, "confirm")},
                 {"id": "reset", "title": _t(locale, "start_over")}],
            )

    # ── 3. Choice ────────────────────────────────────────────────────────────
    if ask and ask.type == "choice" and ask.options:
        opts = _enrich_options(ask.options)
        n = len(opts)

        # Trip options (time-format labels) always use list so description is
        # visible inside the clickable row, even when there are only 1-3 trips.
        is_trip_list = any(
            re.search(r"\d{2}:\d{2}\s*[→>-]\s*\d{2}:\d{2}", o.label or "")
            for o in opts
        )

        if n <= 3 and not is_trip_list:
            buttons = [{"id": o.value, "title": _trunc(o.label, 20)} for o in opts]
            body = say
            desc_lines = [
                f"*{o.label}*\n_{o.description}_"
                for o in opts if (o.description or "").strip()
            ]
            if desc_lines:
                body = say + "\n\n" + "\n\n".join(desc_lines)
            return _wa_buttons(wa_to, body, buttons)

        # Trip options + 4-100 options: interactive list with context-aware labels
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
