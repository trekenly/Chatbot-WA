import React, { useMemo } from "react";

function pick(obj: any, keys: string[]): string {
  for (const k of keys) {
    const v = obj?.[k];
    if (v === undefined || v === null) continue;
    const s = String(v).trim();
    if (s) return s;
  }
  return "";
}

function prettyDate(raw: string): string {
  const s = String(raw || "").trim();
  const m = s.match(/^(\d{4}-\d{2}-\d{2})/);
  return m ? m[1] : s;
}

export function BookingSummaryPanel(props: {
  serverState: Record<string, unknown>;
  reservation: any | null;
  passenger: any | null;
}) {
  const { serverState, reservation, passenger } = props;

  const model = useMemo(() => {
    const s: any = serverState || {};

    const date = pick(s, ["departure_date", "date", "travel_date"]);
    const to = pick(s, ["to", "to_name", "to_place", "to_station"]);
    const from = pick(s, ["from", "from_name", "from_place", "from_station"]);
    const pax = pick(s, ["pax", "passengers", "num_passengers", "pax_count"]);

    // Trip-ish
    const trip = pick(s, ["trip", "trip_name", "trip_id", "route", "route_id", "departure_time"]);

    // Seat(s)
    const seats = (() => {
      const v = s.seats || s.seat || s.seat_no || s.selected_seat || s.selectedSeat;
      if (Array.isArray(v)) return v.map((x) => String(x)).filter(Boolean).join(", ");
      return v ? String(v) : "";
    })();

    const reservationId = pick(reservation, ["reservationId", "reservation_id"])
      || pick(s, ["reservation_id", "booking_id", "bookingId"]);

    const amount = pick(reservation, ["amount"]);
    const currency = pick(reservation, ["currency"]);

    const pName = (() => {
      const p: any = passenger || {};
      const first = String(p.firstName || p.first_name || "").trim();
      const last = String(p.lastName || p.last_name || "").trim();
      const full = String(p.fullName || p.full_name || "").trim();
      return [first, last].filter(Boolean).join(" ") || full;
    })();
    const email = pick(passenger, ["email"]);
    const phone = pick(passenger, ["phone"]);

    return {
      date: date ? prettyDate(date) : "",
      from,
      to,
      pax,
      trip,
      seats,
      reservationId,
      amount: amount && currency ? `${amount} ${currency}` : amount || "",
      passengerName: pName,
      email,
      phone,
    };
  }, [serverState, reservation, passenger]);

  const hasAnything = Object.values(model).some((v) => String(v || "").trim().length > 0);
  if (!hasAnything) return null;

  return (
    <aside className="summary" aria-label="Booking summary">
      <div className="summaryCard">
        <div className="summaryTitle">Booking summary</div>
        <div className="summaryGrid">
          {model.date && (
            <div className="summaryRow">
              <div className="summaryLabel">Date</div>
              <div className="summaryValue">{model.date}</div>
            </div>
          )}
          {(model.from || model.to) && (
            <div className="summaryRow">
              <div className="summaryLabel">Route</div>
              <div className="summaryValue">
                {model.from || "—"} <span className="summaryArrow">→</span> {model.to || "—"}
              </div>
            </div>
          )}
          {model.pax && (
            <div className="summaryRow">
              <div className="summaryLabel">Passengers</div>
              <div className="summaryValue">{model.pax}</div>
            </div>
          )}
          {model.trip && (
            <div className="summaryRow">
              <div className="summaryLabel">Trip</div>
              <div className="summaryValue">{model.trip}</div>
            </div>
          )}
          {model.seats && (
            <div className="summaryRow">
              <div className="summaryLabel">Seats</div>
              <div className="summaryValue mono">{model.seats}</div>
            </div>
          )}
          {model.passengerName && (
            <div className="summaryRow">
              <div className="summaryLabel">Passenger</div>
              <div className="summaryValue">{model.passengerName}</div>
            </div>
          )}
          {(model.email || model.phone) && (
            <div className="summaryRow">
              <div className="summaryLabel">Contact</div>
              <div className="summaryValue">
                {model.phone && <span className="summaryPill mono">{model.phone}</span>}
                {model.email && <span className="summaryPill">{model.email}</span>}
              </div>
            </div>
          )}
          {model.reservationId && (
            <div className="summaryRow">
              <div className="summaryLabel">Reservation</div>
              <div className="summaryValue mono">{model.reservationId}</div>
            </div>
          )}
          {model.amount && (
            <div className="summaryRow">
              <div className="summaryLabel">Amount</div>
              <div className="summaryValue">{model.amount}</div>
            </div>
          )}
        </div>
      </div>
    </aside>
  );
}
