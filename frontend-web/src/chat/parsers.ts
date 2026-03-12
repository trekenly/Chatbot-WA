// Central parsers for legacy backend text blocks.
// Keeping these out of UI components avoids duplication and makes reducer/App consistent.

export type ReservationSummary = {
  passenger?: {
    title?: string;
    gender?: string;
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

export type StatusSummary = {
  reservationId?: string;
  orderRefId?: string;
  amount?: string;
  currency?: string;
  expiresAt?: string;
  payStatus?: string;
};

function parseAmountLine(amountLine?: string): { amount?: string; currency?: string } {
  const line = String(amountLine || "").trim();
  if (!line) return {};
  const m = line.match(/^([0-9.,]+)\s*([A-Z]{3})?/);
  if (!m) return {};
  return { amount: m[1], currency: m[2] || undefined };
}

// Example reservation block:
// "Reservation created.\nreservation_id: ...\norder_ref_id: ...\namount: 1000.00 THB\nexpires_at: ..."
export function parseReservationCard(text: string): ReservationSummary | null {
  const t = String(text || "");
  if (!/Reservation created/i.test(t)) return null;

  const reservationId = (t.match(/reservation_id\s*:\s*([^\s]+)/i) || [])[1];
  const orderRefId = (t.match(/order_ref_id\s*:\s*([^\s]+)/i) || [])[1];
  const amountLine = (t.match(/amount\s*:\s*([^\n]+)/i) || [])[1];
  const { amount, currency } = parseAmountLine(amountLine);

  const expiresAt = (t.match(/expires_at\s*:\s*([^\n]+)/i) || [])[1]?.trim();

  const departure = (t.match(/\bdeparture\s*:\s*([^\n]+)/i) || [])[1]?.trim();
  const destination = (t.match(/\bdestination\s*:\s*([^\n]+)/i) || [])[1]?.trim();

  return { reservationId, orderRefId, amount, currency, expiresAt, departure, destination };
}

// Example status block:
// "reservation_id: ...\norder_ref_id: ...\namount: 1050.00 THB\npay_status: N\nexpires_at: 2026-..."
export function parseStatusCard(text: string): StatusSummary | null {
  const t = String(text || "");
  if (!/(pay_status|pay status)/i.test(t)) return null;

  const reservationId = (t.match(/reservation_id\s*:\s*([^\s]+)/i) || [])[1];
  const orderRefId = (t.match(/order_ref_id\s*:\s*([^\s]+)/i) || [])[1];
  const amountLine = (t.match(/amount\s*:\s*([^\n]+)/i) || [])[1];
  const { amount, currency } = parseAmountLine(amountLine);

  const payStatus = (t.match(/pay_status\s*:\s*([^\n]+)/i) || [])[1]?.trim();
  const expiresAt = (t.match(/expires_at\s*:\s*([^\n]+)/i) || [])[1]?.trim();

  return { reservationId, orderRefId, amount, currency, expiresAt, payStatus };
}
