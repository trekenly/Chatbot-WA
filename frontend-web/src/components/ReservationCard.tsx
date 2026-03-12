import React, { useMemo, useState } from "react";

export type ReservationSummary = {
  passenger?: {
    title?: string; // "Mr"/"Ms"
    gender?: string; // "M"/"F"
    firstName?: string;
    fullName?: string;
    lastName?: string;
    email?: string;
    phone?: string;
  };
  reservationId?: string;
  orderRefId?: string;
  amount?: string;
  currency?: string;
  expiresAt?: string;
  departure?: string;
  destination?: string;
};

// Very small parser that recognizes the legacy text block emitted by the backend.
// Example:
// "Reservation created.\nreservation_id: ...\norder_ref_id: ...\namount: 1000.00 THB\nexpires_at: ..."
export function parseReservationCard(text: string): ReservationSummary | null {
  const t = String(text || "");
  if (!/Reservation created/i.test(t)) return null;

  const reservationId = (t.match(/reservation_id\s*:\s*([^\s]+)/i) || [])[1];
  const orderRefId = (t.match(/order_ref_id\s*:\s*([^\s]+)/i) || [])[1];
  const amountLine = (t.match(/amount\s*:\s*([^\n]+)/i) || [])[1];
  let amount: string | undefined;
  let currency: string | undefined;
  if (amountLine) {
    const m = amountLine.trim().match(/^([0-9.,]+)\s*([A-Z]{3})?/);
    if (m) {
      amount = m[1];
      currency = m[2] || undefined;
    }
  }
  const expiresAt = (t.match(/expires_at\s*:\s*([^\n]+)/i) || [])[1]?.trim();

  const departure = (t.match(/\bdeparture\s*:\s*([^\n]+)/i) || [])[1]?.trim();
  const destination = (t.match(/\bdestination\s*:\s*([^\n]+)/i) || [])[1]?.trim();

  return { reservationId, orderRefId, amount, currency, expiresAt, departure, destination };
}


function formatExpires(raw?: string) {
  const s = String(raw || "").trim();
  if (!s) return "";
  // Prefer a compact display: YYYY-MM-DD HH:MM (keep timezone if present)
  const m = s.match(/^(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2})/);
  if (m) return `${m[1]} ${m[2]}`;
  return s;
}

function formatName(p?: ReservationSummary["passenger"]): string {
  if (!p) return "";
  const title = (p.title || "").trim();
  const first = (p.firstName || "").trim();
  const last = (p.lastName || "").trim();
  const full = (p.fullName || "").trim();
  const name = [first, last].filter(Boolean).join(" ").trim() || full;
  return [title, name].filter(Boolean).join(" ").trim();
}

export function ReservationCard(props: {
  data: ReservationSummary;
  disabled?: boolean;
  onPay?: () => void;
  onStatus?: () => void;
  onCancel?: () => void;
  onRefund?: () => void;
}) {
  const { data, disabled, onPay, onStatus, onCancel, onRefund } = props;
  const [open, setOpen] = useState(false);

  const personName = useMemo(() => formatName(data.passenger), [data.passenger]);
  const hasManage = Boolean(onCancel || onRefund);

  return (
    <div className="resCard">
      <div className="resHead">
        <div className="resHeadLeft">
          <div className="resTitle">Reservation created</div>
          {personName && <div className="resName">{personName}</div>}
        </div>

        <div className="resBadge" aria-label="Reservation created">✓</div>
      </div>

      <div className="resDivider" />

      <div className="resGrid">
        {(data.departure || data.destination) && (
          <div className="resRoute" style={{ gridColumn: "1 / -1" }}>
            <div className="resLabel">Route</div>
            <div className="resValue">
              {data.departure && (
                <div>
                  <span className="mono" style={{ opacity: 0.8 }}>From:</span> {data.departure}
                </div>
              )}
              {data.destination && (
                <div>
                  <span className="mono" style={{ opacity: 0.8 }}>To:</span> {data.destination}
                </div>
              )}
            </div>
          </div>
        )}

        {data.reservationId && (
          <div>
            <div className="resLabel">Reservation ID</div>
            <div className="resValue mono">{data.reservationId}</div>
          </div>
        )}
        {data.orderRefId && (
          <div>
            <div className="resLabel">Order Ref</div>
            <div className="resValue mono">{data.orderRefId}</div>
          </div>
        )}
        {(data.amount || data.currency) && (
          <div>
            <div className="resLabel">Amount</div>
            <div className="resValue">
              {data.amount} {data.currency}
            </div>
          </div>
        )}
        {data.expiresAt && (
          <div>
            <div className="resLabel">Expires</div>
            <div className="resValue">{formatExpires(data.expiresAt)}</div>
          </div>
        )}

        {data.passenger && (
          <div className="resPerson">
            <div className="resLabel">Passenger</div>
            <div className="resValue">{formatName(data.passenger)}</div>
            <div className="resMeta">
              {data.passenger.phone && <span className="resMetaItem">{data.passenger.phone}</span>}
              {data.passenger.email && <span className="resMetaItem">{data.passenger.email}</span>}
            </div>
          </div>
        )}
      </div>

      <div className="resActions">
        <button className="btn btnPrimary" type="button" disabled={disabled} onClick={onPay}>
          Pay now
        </button>
        <button className="btn btnGhost" type="button" disabled={disabled} onClick={onStatus}>
          Check status
        </button>

        {hasManage && (
          <div className="manageWrap">
            <button
              className="btn btnGhost"
              type="button"
              disabled={disabled}
              onClick={() => setOpen((v) => !v)}
            >
              Manage ▾
            </button>

            {open && (
              <div className="manageMenu" role="menu">
                {onCancel && (
                  <button
                    className="manageItem"
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      setOpen(false);
                      onCancel();
                    }}
                  >
                    Cancel
                  </button>
                )}
                {onRefund && (
                  <button
                    className="manageItem"
                    type="button"
                    disabled={disabled}
                    onClick={() => {
                      setOpen(false);
                      onRefund();
                    }}
                  >
                    Refund
                  </button>
                )}
              </div>
            )}
          </div>
        )}
      </div>

      <div className="resHint">
        You can also type <b>pay</b> or <b>status</b>.
      </div>
    </div>
  );
}
