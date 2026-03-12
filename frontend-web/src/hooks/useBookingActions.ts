/**
 * useBookingActions
 *
 * Encapsulates the cancel / refund / reset flows so App.tsx only deals with
 * rendering.  All mutations go through the same inFlightRef guard that the
 * parent provides.
 */
import type { MutableRefObject } from "react";
import { postJSON } from "../lib/api";
import type { ChatState } from "../chat/types";
import type { Action } from "../chat/reducer";
import { computeAskSig } from "../chat/selectors";
import { sendText } from "../chat/engine";

type Dispatch = (action: Action) => void;

export type BookingActions = {
  doCancelReservation: () => Promise<void>;
  doRefundOrCancel: () => Promise<void>;
  softResetToStart: (opts?: { force?: boolean }) => Promise<void>;
};

export function useBookingActions(args: {
  endpoint: string;
  userId: string;
  stateRef: MutableRefObject<ChatState>;
  inFlightRef: MutableRefObject<boolean>;
  dispatch: Dispatch;
  send: (text: string, opts?: { echoUser?: boolean; force?: boolean }) => Promise<void>;
}): BookingActions {
  const { endpoint, userId, stateRef, inFlightRef, dispatch, send } = args;

  function getBookingId(): string | null {
    const s = stateRef.current.serverState as Record<string, unknown>;
    const id = s.reservation_id ?? s.booking_id ?? s.bookingId ?? null;
    return id != null ? String(id) : null;
  }

  async function softResetToStart(opts?: { force?: boolean }) {
    if (!opts?.force) {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
    }
    dispatch({ type: "BOOT_START", pendingAskSig: computeAskSig(stateRef.current.ask) });
    try {
      const env = await sendText({ endpoint, userId, text: "reset", state: {} });
      dispatch({
        type: "BOOT_OK",
        env,
        cachedChoice: stateRef.current.cachedChoice,
        lastPassenger: stateRef.current.lastPassenger,
      });
    } finally {
      if (!opts?.force) inFlightRef.current = false;
    }
  }

  async function doCancelReservation() {
    const bookingId = getBookingId();
    if (!bookingId) {
      await send("I couldn't find a reservation to cancel.", { echoUser: false });
      return;
    }
    if (!window.confirm("Cancel this reservation and release the seats?")) return;
    if (inFlightRef.current) return;
    inFlightRef.current = true;

    try {
      const res = await postJSON<{ success?: boolean }>("/buyer/cancel_reservation", {
        state: stateRef.current.serverState,
        booking_id: bookingId,
      });
      inFlightRef.current = false;
      const msg = res?.success ? "✅ Reservation cancelled." : "Reservation cancellation sent.";
      await send(msg, { echoUser: false, force: true });
      await softResetToStart({ force: true });
    } catch (e: unknown) {
      inFlightRef.current = false;
      const msg = e instanceof Error ? e.message : String(e);
      await send(`Cancel failed: ${msg}`, { echoUser: false, force: true });
    } finally {
      inFlightRef.current = false;
    }
  }

  async function doRefundOrCancel() {
    const bookingId = getBookingId();
    if (!bookingId) {
      await send("I couldn't find a booking to manage.", { echoUser: false });
      return;
    }
    if (inFlightRef.current) return;
    inFlightRef.current = true;

    try {
      type DetailsResp = {
        data?: {
          order?: { payment?: { payment_status?: string; status?: string } };
          reservations?: Array<{ global_ticket_number?: string }>;
          global_ticket_number?: string;
        };
      };

      const details = await postJSON<DetailsResp>("/buyer/reservation_details", {
        state: stateRef.current.serverState,
        booking_id: bookingId,
      });

      const pay = details?.data?.order?.payment;
      const payStatus = String(pay?.payment_status ?? pay?.status ?? "").trim().toUpperCase();
      const reservations = details?.data?.reservations ?? [];
      const first = Array.isArray(reservations) ? reservations[0] : null;
      const gtn = first?.global_ticket_number ?? details?.data?.global_ticket_number ?? null;

      const isPaid = payStatus === "Y" || payStatus === "PAID" || payStatus === "SUCCESS";

      if (gtn && isPaid) {
        if (!window.confirm("Request a refund for this ticket?")) return;

        const req = await postJSON<{ data?: unknown }>("/buyer/request_refund", {
          global_ticket_number: String(gtn),
        });

        const row = Array.isArray(req?.data) ? (req.data as Record<string, unknown>[])[0] : (req?.data as Record<string, unknown> | undefined);
        const allow = String((row as Record<string, unknown> | undefined)?.allow_refund ?? "").trim().toUpperCase();
        const refundRefId = (row as Record<string, unknown> | undefined)?.refund_ref_id ?? null;

        if (allow !== "Y" || !refundRefId) {
          await send("Refund isn't available for this ticket.", { echoUser: false });
          return;
        }

        const res = await postJSON<{ success?: boolean }>("/buyer/create_refund", {
          refund_ref_id: String(refundRefId),
        });
        inFlightRef.current = false;
        const msg = res?.success ? "✅ Refund requested." : "Refund request sent.";
        await send(msg, { echoUser: false, force: true });
        await softResetToStart({ force: true });
        return;
      }

      // Unpaid — just cancel (release seats).
      await doCancelReservation();
    } catch (e: unknown) {
      inFlightRef.current = false;
      const msg = e instanceof Error ? e.message : String(e);
      await send(`Couldn't manage booking: ${msg}`, { echoUser: false, force: true });
    } finally {
      inFlightRef.current = false;
    }
  }

  return { doCancelReservation, doRefundOrCancel, softResetToStart };
}
