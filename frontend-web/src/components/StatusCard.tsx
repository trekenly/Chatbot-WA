import React, { useMemo } from "react";

export type StatusSummary = {
  reservationId?: string;
  orderRefId?: string;
  amount?: string;
  currency?: string;
  expiresAt?: string;
  payStatus?: string; // 'Y' | 'N' | etc
};

// Parses the legacy status text block emitted by the backend.
// Example:
// "reservation_id: ...\norder_ref_id: ...\namount: 1050.00 THB\npay_status: N\nexpires_at: 2026-..."
export function parseStatusCard(text: string): StatusSummary | null {
  const t = String(text || "");
  // Heuristic: status blocks usually contain pay_status/pay status
  if (!/(pay_status|pay status)/i.test(t)) return null;

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
  const payStatus = (t.match(/pay_status\s*:\s*([^\n]+)/i) || [])[1]?.trim();
  const expiresAt = (t.match(/expires_at\s*:\s*([^\n]+)/i) || [])[1]?.trim();

  return { reservationId, orderRefId, amount, currency, expiresAt, payStatus };
}

function formatExpires(raw?: string) {
  const s = String(raw || "").trim();
  if (!s) return "";
  const m = s.match(/^(\d{4}-\d{2}-\d{2})[T\s](\d{2}:\d{2})/);
  if (m) return `${m[1]} ${m[2]}`;
  return s;
}

function formatPayStatus(raw?: string) {
  const s = String(raw || "").trim().toUpperCase();
  if (!s) return { label: "Unknown", kind: "unknown" as const };
  if (s === "Y" || s === "PAID" || s === "SUCCESS") return { label: "Paid", kind: "paid" as const };
  if (s === "N" || s === "PENDING" || s === "UNPAID") return { label: "Pending payment", kind: "pending" as const };
  if (s === "C" || s === "CANCEL" || s === "CANCELLED") return { label: "Cancelled", kind: "cancel" as const };
  return { label: s, kind: "unknown" as const };
}

export function StatusCard(props: {
  data: StatusSummary;
  disabled?: boolean;
  onPay?: () => void;
  onRefresh?: () => void;
}) {
  const { data, disabled, onPay, onRefresh } = props;
  const st = useMemo(() => formatPayStatus(data.payStatus), [data.payStatus]);
  const badgeClass =
    st.kind === "paid"
      ? "resBadge resBadgePaid"
      : st.kind === "pending"
        ? "resBadge resBadgePending"
        : st.kind === "cancel"
          ? "resBadge resBadgeCancel"
          : "resBadge";

  return (
    <div className="resCard statusCard">
      <div className="resHead">
        <div className="resHeadLeft">
          <div className="resTitle">Payment status</div>
          <div className="resName">{st.label}</div>
        </div>
        <div className={badgeClass} aria-label={st.label}>
          {st.kind === "paid" ? "✓" : st.kind === "pending" ? "…" : st.kind === "cancel" ? "×" : "?"}
        </div>
      </div>

      <div className="resDivider" />

      <div className="resGrid">
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
      </div>

      <div className="resActions">
        {st.kind !== "paid" && (
          <button className="btn btnPrimary" type="button" disabled={disabled} onClick={onPay}>
            Pay now
          </button>
        )}
        <button className="btn btnGhost" type="button" disabled={disabled} onClick={onRefresh}>
          Refresh
        </button>
      </div>

      <div className="resHint">You can also type <b>status</b>.</div>
    </div>
  );
}
