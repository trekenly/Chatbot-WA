# app/busx/client.py
from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from app.busx import endpoints
from app.busx.auth import get_access_token


# -----------------------------
# Env helpers
# -----------------------------

def _env_str(name: str, default: str) -> str:
    v = (os.getenv(name, default) or default).strip()
    return v or default


def _env_bool(name: str, default: bool = False) -> bool:
    v = (os.getenv(name, "") or "").strip().lower()
    if not v:
        return default
    return v in {"1", "true", "yes", "y", "on"}


def _default_locale() -> str:
    return _env_str("DEFAULT_LOCALE", "en_US")


def _default_currency() -> str:
    return _env_str("DEFAULT_CURRENCY", "THB")


# -----------------------------
# Client
# -----------------------------

class BusXClient:
    """
    Thin wrapper over BusX GDS.

    Token placement (per v2.17 behavior described in your project):
      - GET endpoints: access_token in query params
      - POST form endpoints: access_token in form body
      - POST JSON endpoints: access_token in JSON body

    Some BusX environments historically accepted access_token in BOTH query+body for JSON POST.
    If you MUST support that, set:
      BUSX_TOKEN_IN_QUERY_FOR_JSON=1
    """

    def __init__(self) -> None:
        timeout = httpx.Timeout(15.0, connect=5.0)
        self._client = httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers={"Accept": "application/json"},
        )
        self._token_in_query_for_json = _env_bool("BUSX_TOKEN_IN_QUERY_FOR_JSON", False)

    async def close(self) -> None:
        await self._client.aclose()

    async def __aenter__(self) -> "BusXClient":
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def _token(self) -> str:
        return await get_access_token(self._client)

    @staticmethod
    def _redact_sent(sent: Any) -> Any:
        """Remove access_token from logged payloads."""
        if isinstance(sent, dict):
            return {
                k: ({kk: ("***" if kk == "access_token" else vv) for kk, vv in v.items()} if isinstance(v, dict) else v)
                for k, v in sent.items()
            }
        return sent

    def _raise_with_detail(self, url: str, r: httpx.Response, *, sent: Any) -> None:
        try:
            detail: Any = r.json()
        except Exception:
            detail = r.text

        raise RuntimeError(
            f"BusX API error for {url}: {r.status_code} {r.reason_phrase} | detail={detail} | sent={self._redact_sent(sent)}"
        )

    # ---------------------------
    # Low-level request helpers
    # ---------------------------

    async def _get(
        self,
        url: str,
        *,
        params: Optional[Dict[str, Any]] = None,
        locale: Optional[str] = None,
    ) -> Any:
        token = await self._token()
        q: Dict[str, Any] = {"access_token": token, "locale": (locale or _default_locale())}

        if params:
            q.update(params)

        r = await self._client.get(url, params=q)
        if r.status_code >= 400:
            self._raise_with_detail(url, r, sent={"params": q})
        return r.json()

    async def _post_form(
        self,
        url: str,
        *,
        data: Dict[str, Any],
        locale: Optional[str] = None,
        include_currency: bool = False,
        currency: Optional[str] = None,
    ) -> Any:
        token = await self._token()
        form: Dict[str, Any] = {"access_token": token, "locale": (locale or _default_locale())}

        if include_currency:
            form["currency"] = currency or _default_currency()

        form.update(data)

        r = await self._client.post(url, data=form)
        if r.status_code >= 400:
            self._raise_with_detail(url, r, sent={"form": form})
        return r.json()

    async def _post_json(
        self,
        url: str,
        *,
        payload: Dict[str, Any],
        locale: Optional[str] = None,
        include_currency: bool = False,
        currency: Optional[str] = None,
    ) -> Any:
        token = await self._token()

        body: Dict[str, Any] = {
            "access_token": token,
            "locale": (locale or _default_locale()),
        }
        if include_currency:
            body["currency"] = currency or _default_currency()

        body.update(payload)

        # Optional legacy behavior: token also in query
        params = {"access_token": token} if self._token_in_query_for_json else None

        r = await self._client.post(url, params=params, json=body)
        if r.status_code >= 400:
            self._raise_with_detail(url, r, sent={"params": params, "json": body})
        return r.json()

    # ---------------------------
    # Public API: Keywords / Trips
    # ---------------------------

    async def list_keyword_from(self, *, locale: Optional[str] = None) -> Any:
        return await self._get(endpoints.LIST_KEYWORD_FROM, locale=locale)

    async def list_keyword_to(
        self,
        *,
        from_keyword_id: Optional[int] = None,
        locale: Optional[str] = None,
    ) -> Any:
        params: Dict[str, Any] = {}
        if from_keyword_id is not None:
            params["from_keyword_id"] = int(from_keyword_id)
        return await self._get(endpoints.LIST_KEYWORD_TO, params=params, locale=locale)

    async def search_trips(
        self,
        *,
        journey_type: str,
        departure_date: str,
        from_keyword_id: int,
        to_keyword_id: int,
        currency: Optional[str] = None,
        return_date: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> Any:
        # Per docs: form-encoded
        data: Dict[str, Any] = {
            "journey_type": journey_type,
            "departure_date": departure_date,
            "from_keyword_id": int(from_keyword_id),
            "to_keyword_id": int(to_keyword_id),
            # doc expects currency in payload for search_trips
            "currency": currency or _default_currency(),
        }
        if return_date:
            data["return_date"] = return_date

        # currency already included in data; don't auto-inject currency field twice
        return await self._post_form(endpoints.SEARCH_TRIPS, data=data, locale=locale, include_currency=False)

    async def get_seat_layouts(
        self,
        *,
        fare_ref_id: str,
        trip_id: Optional[str] = None,
        locale: Optional[str] = None,
        extra: Optional[Dict[str, Any]] = None,
    ) -> Any:
        params: Dict[str, Any] = {"fare_ref_id": fare_ref_id}
        if trip_id:
            params["trip_id"] = trip_id
        if extra:
            params.update(extra)

        return await self._get(endpoints.GET_SEAT_LAYOUTS, params=params, locale=locale)

    # ---------------------------
    # Booking flow
    # ---------------------------

    async def create_checkouts(
        self,
        *,
        fare_ref_id: str,
        adult_count: int,
        child_count: Optional[int] = None,
        infant_count: Optional[int] = None,
        locale: Optional[str] = None,
        currency: Optional[str] = None,
    ) -> Any:
        """
        create_checkouts (POST, JSON)

        Doc shape:
          {
            "access_token": "...",
            "departure": { "fare_ref_id": "..." },
            "adult_count": 2,
            "currency": "THB",
            "locale": "en_US"
          }
        """
        payload: Dict[str, Any] = {
            "departure": {"fare_ref_id": fare_ref_id},
            "adult_count": int(adult_count),
        }
        if child_count is not None:
            payload["child_count"] = int(child_count)
        if infant_count is not None:
            payload["infant_count"] = int(infant_count)

        return await self._post_json(
            endpoints.CREATE_CHECKOUTS,
            payload=payload,
            locale=locale,
            currency=currency,
            include_currency=True,
        )

    async def mark_seats(
        self,
        *,
        fare_ref_id: str,
        passenger_type_code: str,
        gender: str,
        seat_number: str,
        seat_floor: int = 1,
        locale: Optional[str] = None,
    ) -> Any:
        """
        mark_seats (POST, JSON)
        """
        payload: Dict[str, Any] = {
            "fare_ref_id": fare_ref_id,
            "passenger_type_code": passenger_type_code,
            "gender": gender,
            "seat_number": seat_number,
            "seat_floor": int(seat_floor),
        }
        return await self._post_json(endpoints.MARK_SEATS, payload=payload, locale=locale, include_currency=False)




    async def unmark_seats(
        self,
        *,
        fare_ref_id: str,
        seat_event_ids: list[str],
        locale: Optional[str] = None,
    ) -> Any:
        """unmark_seats (POST, JSON) — release previously held seats."""
        payload: Dict[str, Any] = {
            "fare_ref_id": str(fare_ref_id),
            "seat_event_ids": [{"seat_event_id": str(x)} for x in (seat_event_ids or [])],
        }
        return await self._post_json(endpoints.UNMARK_SEATS, payload=payload, locale=locale, include_currency=False)

    
    async def create_reservations(
        self,
        *,
        fare_ref_id: str,
        reservations: list[dict],
        contact_title_id: int,
        contact_name: str,
        contact_email: str,
        contact_phone_country: str,
        contact_phone_number: str,
        departure_ref_id: Optional[str] = None,
        locale: Optional[str] = None,
        currency: Optional[str] = None,
        time_zone: Optional[str] = None,
    ) -> Any:
        """create_reservations (POST, JSON)

        Note: BusX GDS expects reservation data nested under a `departure` object.
        Some providers also require `departure_ref_id` from a prior checkout call.
        """
        departure: Dict[str, Any] = {
            "fare_ref_id": str(fare_ref_id),
            "reservations": reservations,
        }
        if departure_ref_id:
            departure["departure_ref_id"] = str(departure_ref_id)

        payload: Dict[str, Any] = {
            "contact": {
                "contact_title_id": int(contact_title_id),
                "contact_name": contact_name,
                "contact_email": contact_email,
                "contact_phone_country": contact_phone_country,
                "contact_phone_number": contact_phone_number,
            },
            "departure": departure,
        }
        if time_zone:
            payload["time_zone"] = time_zone

        return await self._post_json(
            endpoints.CREATE_RESERVATIONS,
            payload=payload,
            locale=locale,
            currency=currency,
            include_currency=True,
        )

    async def create_payments(
        self,
        *,
        order_ref_id: str,
        locale: Optional[str] = None,
    ) -> Any:
        """create_payments (POST, JSON) — initiate payment."""
        payload: Dict[str, Any] = {"order_ref_id": order_ref_id}
        return await self._post_json(endpoints.CREATE_PAYMENTS, payload=payload, locale=locale, include_currency=False)

    async def get_reservation_details(
        self,
        *,
        booking_id: Optional[str] = None,
        global_ticket_number: Optional[str] = None,
        time_zone: Optional[str] = None,
        locale: Optional[str] = None,
    ) -> Any:
        """get_reservation_details (GET). Provide booking_id OR global_ticket_number."""
        if not booking_id and not global_ticket_number:
            raise ValueError("get_reservation_details requires booking_id or global_ticket_number")

        params: Dict[str, Any] = {}
        if booking_id:
            params["booking_id"] = booking_id
        if global_ticket_number:
            params["global_ticket_number"] = global_ticket_number
        if time_zone:
            params["time_zone"] = time_zone

        return await self._get(endpoints.GET_RESERVATION_DETAILS, params=params, locale=locale)

    async def get_tickets(
        self,
        *,
        booking_id: str,
        ticket_format: str = "json",
        locale: Optional[str] = None,
    ) -> Any:
        """get_tickets (GET). ticket_format: html|json|pdf (default json)."""
        params: Dict[str, Any] = {"booking_id": str(booking_id)}
        if ticket_format:
            params["ticket_format"] = ticket_format
        return await self._get(endpoints.GET_TICKETS, params=params, locale=locale)

    # ---------------------------
    # Cancel / Refund
    # ---------------------------

    async def cancel_reservations(
        self,
        *,
        booking_id: str,
        locale: Optional[str] = None,
    ) -> Any:
        """cancel_reservations (POST, JSON)"""
        payload: Dict[str, Any] = {"booking_id": str(booking_id)}
        return await self._post_json(endpoints.CANCEL_RESERVATIONS, payload=payload, locale=locale, include_currency=False)

    async def request_refunds(
        self,
        *,
        global_ticket_numbers: list[str],
        locale: Optional[str] = None,
    ) -> Any:
        """request_refunds (POST, JSON)"""
        payload: Dict[str, Any] = {
            "global_ticket_numbers": [{"global_ticket_number": str(x)} for x in (global_ticket_numbers or [])]
        }
        return await self._post_json(endpoints.REQUEST_REFUNDS, payload=payload, locale=locale, include_currency=False)

    async def create_refunds(
        self,
        *,
        refund_ref_ids: list[str],
        locale: Optional[str] = None,
    ) -> Any:
        """create_refunds (POST, JSON)"""
        payload: Dict[str, Any] = {"refund_ref_ids": [{"refund_ref_id": str(x)} for x in (refund_ref_ids or [])]}
        return await self._post_json(endpoints.CREATE_REFUNDS, payload=payload, locale=locale, include_currency=False)

    # ---------------------------
    # Tickets / Rebooking / Open-ended / Set travel date
    # ---------------------------

    async def request_rebookings(
        self,
        *,
        global_ticket_numbers: list[str],
        locale: Optional[str] = None,
    ) -> Any:
        payload: Dict[str, Any] = {
            "global_ticket_numbers": [{"global_ticket_number": str(x)} for x in (global_ticket_numbers or [])]
        }
        return await self._post_json(endpoints.REQUEST_REBOOKINGS, payload=payload, locale=locale, include_currency=False)

    async def request_open_ended_ticket(
        self,
        *,
        global_ticket_numbers: list[str],
        locale: Optional[str] = None,
    ) -> Any:
        payload: Dict[str, Any] = {
            "global_ticket_numbers": [{"global_ticket_number": str(x)} for x in (global_ticket_numbers or [])]
        }
        return await self._post_json(endpoints.REQUEST_OPEN_ENDED_TICKET, payload=payload, locale=locale, include_currency=False)

    async def create_open_ended_ticket(
        self,
        *,
        open_ref_ids: list[str],
        locale: Optional[str] = None,
    ) -> Any:
        payload: Dict[str, Any] = {"open_ref_ids": [{"open_ref_id": str(x)} for x in (open_ref_ids or [])]}
        return await self._post_json(endpoints.CREATE_OPEN_ENDED_TICKET, payload=payload, locale=locale, include_currency=False)

    async def request_set_travel_date(
        self,
        *,
        new_fare_ref_id: str,
        old_global_ticket_numbers: list[dict],
        locale: Optional[str] = None,
    ) -> Any:
        """request_set_travel_date (POST, JSON)"""
        payload: Dict[str, Any] = {
            "departure": {
                "new_fare_ref_id": str(new_fare_ref_id),
                "old_global_ticket_numbers": [
                    {
                        "global_ticket_number": str(it.get("global_ticket_number")),
                        "seat_event_id": str(it.get("seat_event_id")),
                    }
                    for it in (old_global_ticket_numbers or [])
                    if it and it.get("global_ticket_number") and it.get("seat_event_id")
                ],
            }
        }
        return await self._post_json(endpoints.REQUEST_SET_TRAVEL_DATE, payload=payload, locale=locale, include_currency=False)

    async def create_set_travel_date(
        self,
        *,
        rebooking_ref_ids: list[str],
        locale: Optional[str] = None,
    ) -> Any:
        payload: Dict[str, Any] = {
            "rebooking_ref_ids": [{"rebooking_ref_id": str(x)} for x in (rebooking_ref_ids or [])]
        }
        return await self._post_json(endpoints.CREATE_SET_TRAVEL_DATE, payload=payload, locale=locale, include_currency=False)
