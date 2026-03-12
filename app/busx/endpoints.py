# app/busx/endpoints.py
#
# Centralized BusX endpoint definitions.
# Keep this file boring + predictable: all URLs are absolute, no double-slashes,
# and older constant names remain for backward compatibility.

from __future__ import annotations

# -----------------------------
# Base URLs
# -----------------------------

# Accounts (JWT)
ACCOUNTS_BASE = "https://accounts.busx.com/api/jwt"

# GDS API base (path includes version segment)
GDS_BASE = "https://gds.busx.com/api/v2.0"


def _join(base: str, path: str) -> str:
    """Join base + path safely (avoids accidental double slashes)."""
    return f"{base.rstrip('/')}/{path.lstrip('/')}"


# -----------------------------
# Auth
# -----------------------------

ACCESS_TOKEN = _join(ACCOUNTS_BASE, "access_token.php")
REFRESH_TOKEN = _join(ACCOUNTS_BASE, "refresh_token.php")


# -----------------------------
# Discovery / search
# -----------------------------

LIST_KEYWORD_FROM = _join(GDS_BASE, "list_keyword_from")
LIST_KEYWORD_TO = _join(GDS_BASE, "list_keyword_to")
SEARCH_TRIPS = _join(GDS_BASE, "search_trips")


# -----------------------------
# Seat layouts
# -----------------------------

GET_SEAT_LAYOUTS = _join(GDS_BASE, "get_seat_layouts")

# Backward compat alias (older code may import SEAT_LAYOUTS)
SEAT_LAYOUTS = GET_SEAT_LAYOUTS


# -----------------------------
# Booking flow
# -----------------------------
# Notes:
# - Your code calls these as "v2.17" behaviors, but the URL path is still /v2.0
#   (versioning appears to be server-side/semantic rather than path-based).

CREATE_CHECKOUTS = _join(GDS_BASE, "create_checkouts")
MARK_SEATS = _join(GDS_BASE, "mark_seats")
UNMARK_SEATS = _join(GDS_BASE, "unmark_seats")
GET_TICKETS = _join(GDS_BASE, "get_tickets")
LIST_CARRIER = _join(GDS_BASE, "list_carrier")
LIST_STOP = _join(GDS_BASE, "list_stop")
LIST_STATE_PROVINCE = _join(GDS_BASE, "list_state_province")
REQUEST_REBOOKINGS = _join(GDS_BASE, "request_rebookings")
REQUEST_OPEN_ENDED_TICKET = _join(GDS_BASE, "request_open_ended_ticket")
CREATE_OPEN_ENDED_TICKET = _join(GDS_BASE, "create_open_ended_ticket")
REQUEST_SET_TRAVEL_DATE = _join(GDS_BASE, "request_set_travel_date")
CREATE_SET_TRAVEL_DATE = _join(GDS_BASE, "create_set_travel_date")

CREATE_RESERVATIONS = _join(GDS_BASE, "create_reservations")
CREATE_PAYMENTS = _join(GDS_BASE, "create_payments")

# Cancel / Refund
CANCEL_RESERVATIONS = _join(GDS_BASE, "cancel_reservations")
REQUEST_REFUNDS = _join(GDS_BASE, "request_refunds")
CREATE_REFUNDS = _join(GDS_BASE, "create_refunds")

# Used by orchestrator status/details refresh
GET_RESERVATION_DETAILS = _join(GDS_BASE, "get_reservation_details")


# Optional: explicit export list to prevent accidental star-import leakage
__all__ = [
    "ACCOUNTS_BASE",
    "GDS_BASE",
    "ACCESS_TOKEN",
    "REFRESH_TOKEN",
    "LIST_KEYWORD_FROM",
    "LIST_KEYWORD_TO",
    "SEARCH_TRIPS",
    "GET_SEAT_LAYOUTS",
    "SEAT_LAYOUTS",
    "CREATE_CHECKOUTS",
    "MARK_SEATS",
    "UNMARK_SEATS",
    "GET_TICKETS",
    "LIST_CARRIER",
    "LIST_STOP",
    "LIST_STATE_PROVINCE",
    "REQUEST_REBOOKINGS",
    "REQUEST_OPEN_ENDED_TICKET",
    "CREATE_OPEN_ENDED_TICKET",
    "REQUEST_SET_TRAVEL_DATE",
    "CREATE_SET_TRAVEL_DATE",
    "CREATE_RESERVATIONS",
    "CREATE_PAYMENTS",
    "CANCEL_RESERVATIONS",
    "REQUEST_REFUNDS",
    "CREATE_REFUNDS",
    "GET_RESERVATION_DETAILS",
]
