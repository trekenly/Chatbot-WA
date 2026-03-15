# app/core/buyer_guide.py
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from app.core.contracts import Action, ChatResponse


@dataclass
class GuidedTurn:
    message: str
    menu: List[Dict[str, Any]]
    expect: Dict[str, Any]
    state: Dict[str, Any]


class BuyerGuide:
    """
    Production UX rules:
    - Don't echo CHOOSE titles into transcript (UI renders menu header).
    - Don't echo ASK prompts into transcript *unless* there is no SAY text at all
      (prevents "(no response)" on ASK-only turns like reset).
    """

    def render(self, resp: ChatResponse) -> GuidedTurn:
        say_lines: List[str] = []
        menu: List[Dict[str, Any]] = []

        expect: Dict[str, Any] = {"type": "text"}

        pending_prompt: Optional[str] = None
        pending_field: Optional[str] = None
        pending_menu_title: Optional[str] = None

        for a in resp.actions or []:
            if isinstance(a, Action):
                a_type = a.type
                payload = a.payload or {}
            else:
                a_type = (a or {}).get("type")
                payload = (a or {}).get("payload") or {}

            if a_type == "say":
                txt = str(payload.get("text") or "").strip()
                if txt:
                    say_lines.append(txt)

            elif a_type == "ask":
                pending_prompt = str(payload.get("prompt") or "").strip() or None
                pending_field = str(payload.get("field") or "").strip() or None

                if pending_field == "passenger_flow":
                    expect = {"type": "passenger_flow", "field": pending_field}
                elif pending_field:
                    expect = {"type": "field", "field": pending_field}
                else:
                    expect = {"type": "text"}

                if pending_prompt:
                    # keep for channels/UI that want to display it
                    expect["prompt"] = pending_prompt

            elif a_type == "choose_one":
                pending_menu_title = str(payload.get("title") or "Choose one").strip() or None
                options = payload.get("options") or []

                menu = []
                for i, opt in enumerate(options, start=1):
                    if isinstance(opt, dict):
                        label = str(opt.get("label") or "").strip()
                        desc = str(opt.get("description") or "").strip()
                        # Preserve explicit string ID (e.g. "pay", "cancel", "change")
                        opt_id = opt.get("id") or i
                    else:
                        label = str(getattr(opt, "label", "") or "").strip()
                        desc = str(getattr(opt, "description", "") or "").strip()
                        opt_id = i

                    if not label:
                        label = f"{i}."
                    menu.append({"i": opt_id, "label": label, "description": desc})

                if menu:
                    expect = {"type": "choice", "min": 1, "max": len(menu), "reply": "number"}
                    if pending_menu_title:
                        expect["title"] = pending_menu_title

            else:
                continue

        # ✅ Transcript message:
        # - Prefer SAY text (normal case)
        # - If no SAY at all (ASK-only or CHOOSE-only), show the prompt/title instead of "(no response)"
        message = "\n\n".join([x for x in say_lines if x.strip()]).strip()
        if not message:
            message = (pending_prompt or pending_menu_title or "").strip()

        # Seat-map hinting (UI-only envelope)
        try:
            st = resp.state or {}
            if str(st.get("step") or "").upper() == "PICK_SEATS":
                pax = st.get("pax")
                selected = st.get("selected_seats") or []
                # Prefer the full seat layout (so the web UI can draw a real seat chart).
                layout = st.get("last_seat_layout") or None
                layout_data = None
                try:
                    if isinstance(layout, dict):
                        layout_data = (layout.get("data") or layout)  # raw BusX response uses .data
                except Exception:
                    layout_data = None

                seats_fallback = st.get("available_seats") or []

                if layout_data and isinstance(layout_data, dict) and layout_data.get("seat_layout_details"):
                    expect = {
                        "type": "seatmap",
                        "pax": int(pax) if str(pax or "").isdigit() else None,
                        "seats": {
                            "trip_id": layout_data.get("trip_id"),
                            "seat_layout_id": layout_data.get("seat_layout_id"),
                            "name": layout_data.get("name"),
                            "floor_amount": layout_data.get("floor_amount"),
                            "floor_details": layout_data.get("floor_details") or [],
                            "seat_layout_details": layout_data.get("seat_layout_details") or [],
                        },
                        "selected": selected if isinstance(selected, list) else [],
                    }
                elif isinstance(seats_fallback, list) and seats_fallback:
                    expect = {
                        "type": "seatmap",
                        "pax": int(pax) if str(pax or "").isdigit() else None,
                        "seats": seats_fallback,
                        "selected": selected if isinstance(selected, list) else [],
                    }
        except Exception:
            pass

        return GuidedTurn(
            message=message,
            menu=menu,
            expect=expect,
            state=resp.state or {},
        )