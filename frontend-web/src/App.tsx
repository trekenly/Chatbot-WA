import { useEffect, useMemo, useReducer, useRef, useState } from "react";
import { ChoiceChips } from "./components/ChoiceChips";
import { TerminalPickerCard } from "./components/TerminalPickerCard";
import { DateQuickChips } from "./components/DateQuickChips";
import { PassengerDetailsCard } from "./components/PassengerDetailsCard";
import { PaxChips } from "./components/PaxChips";
import { QuickToChips } from "./components/QuickPlacesChips";
// QuickFromChips is intentionally not used until multi-city departure is enabled.
import { ReservationCard, parseReservationCard } from "./components/ReservationCard";
import { SeatMapPicker } from "./components/SeatMapPicker";
import { StatusCard, parseStatusCard } from "./components/StatusCard";
import { TypingDots } from "./components/TypingDots";
import { BangkokTerminalPicker } from "./components/BangkokTerminalPicker";

import { sendText } from "./chat/engine";
import { chatReducer, initialChatState } from "./chat/reducer";
import type { PassengerSnap } from "./chat/types";
import { cleanPrompt, computeAskSig } from "./chat/selectors";

import { postJSON } from "./lib/api";
import { readJSON } from "./lib/storage";
import { useBookingActions } from "./hooks/useBookingActions";

const DEFAULT_USER_ID = "web-buyer-1";

function norm(s: string): string {
  return String(s || "")
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9\s]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

function isBangkokInput(s: string): boolean {
  const t = norm(s);
  return t === "bangkok" || t === "bkk" || t === "krung thep" || t === "krungthep";
}

/** Picks the first non-empty string value from an object by a list of key names. */
function pick(obj: unknown, keys: string[]): string {
  for (const k of keys) {
    const v = (obj as Record<string, unknown>)?.[k];
    if (v === undefined || v === null) continue;
    const s = String(v).trim();
    if (s) return s;
  }
  return "";
}

function getQueryParam(name: string): string | null {
  try {
    const v = new URLSearchParams(window.location.search).get(name);
    return v ? v.trim() : null;
  } catch {
    return null;
  }
}

const DEST_KEYS = ["to_label", "desired_to_text", "to_query", "to", "to_name", "to_place", "to_station"];

export default function App() {
  const endpoint = useMemo(
    () => import.meta.env.VITE_BUYER_ENDPOINT || getQueryParam("endpoint") || "/buyer/chat",
    []
  );

  const userId = useMemo(() => getQueryParam("user_id") || DEFAULT_USER_ID, []);
  const debug = useMemo(
    () => new URLSearchParams(window.location.search).get("debug") === "1",
    []
  );

  const passengerCacheKey = useMemo(() => `bx_passenger_details:${userId}`, [userId]);
  const choiceCacheKey = useMemo(() => `bx_choice_cache:${userId}`, [userId]);

  const [state, dispatch] = useReducer(
    chatReducer,
    undefined,
    () =>
      initialChatState({
        cachedChoice: readJSON(choiceCacheKey, { options: [] as any[] }),
        lastPassenger: readJSON<PassengerSnap | null>(passengerCacheKey, null),
        debug,
      })
  );

  // Keep refs for async calls (prevents stale state during rapid taps).
  const stateRef = useRef(state);
  useEffect(() => {
    stateRef.current = state;
  }, [state]);

  const inFlightRef = useRef(false);

  // ─── Cache persistence ───────────────────────────────────────────────────
  useEffect(() => {
    try { localStorage.setItem(choiceCacheKey, JSON.stringify(state.cachedChoice)); } catch { /* ignore */ }
  }, [choiceCacheKey, state.cachedChoice]);

  useEffect(() => {
    try {
      if (state.lastPassenger) localStorage.setItem(passengerCacheKey, JSON.stringify(state.lastPassenger));
    } catch { /* ignore */ }
  }, [passengerCacheKey, state.lastPassenger]);

  // ─── Boot: reset on refresh ──────────────────────────────────────────────
  useEffect(() => {
    let cancelled = false;
    (async () => {
      inFlightRef.current = true;
      dispatch({ type: "BOOT_START", pendingAskSig: computeAskSig(stateRef.current.ask as any) });
      try {
        const env = await sendText({ endpoint, userId, text: "reset", state: {} });
        if (cancelled) return;
        dispatch({ type: "BOOT_OK", env, cachedChoice: stateRef.current.cachedChoice, lastPassenger: stateRef.current.lastPassenger });
      } catch (e: any) {
        if (cancelled) return;
        dispatch({ type: "BOOT_FAIL", errorText: `Sorry — I couldn't start the chat. ${e?.message || e}` });
      } finally {
        if (!cancelled) inFlightRef.current = false;
      }
    })();
    return () => { cancelled = true; };
  }, [endpoint, userId]);

  // ─── Auto-scroll ─────────────────────────────────────────────────────────
  const bottomRef = useRef<HTMLDivElement | null>(null);
  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: "smooth" });
  }, [state.bubbles, state.loading, state.ask]);

  // ─── Composer state ──────────────────────────────────────────────────────
  const [text, setText] = useState("");
  const [composerHint, setComposerHint] = useState<string>("");

  // ─── Bangkok terminal picker state ───────────────────────────────────────
  //
  // Destination-first UX: most travellers don't know which of Bangkok's ~20 bus
  // terminals serves their route. So when the user says "Bangkok" for FROM, we
  // first ask WHERE they're going (locally — no round-trip to the backend), then
  // open the terminal picker with that context so it can highlight the right one.
  //
  //   bkkDestStep        → show the "where are you heading?" step
  //   bkkDestHint        → the destination name captured during that step
  //   pendingBangkokFrom → show the terminal picker itself
  //
  // If serverState already carries a destination we skip straight to the picker.
  const [bkkDestStep, setBkkDestStep] = useState(false);
  const [bkkDestHint, setBkkDestHint] = useState("");
  const [pendingBangkokFrom, setPendingBangkokFrom] = useState(false);
  const [bkkSellableIds, setBkkSellableIds] = useState<string[] | null>(null);
  const [bkkSellableLoading, setBkkSellableLoading] = useState(false);

  // When the terminal picker opens and destination + date are known, ask the
  // backend which terminals actually have sellable routes. Falls back to static
  // mapping if the endpoint returns nothing.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      if (!pendingBangkokFrom) return;

      const s = stateRef.current.serverState as Record<string, unknown>;
      const toId    = s.to_keyword_id ?? s.toKeywordId ?? null;
      const depDate = s.departure_date ?? s.departureDate ?? null;

      setBkkSellableIds(null);
      if (!toId || !depDate) return;

      setBkkSellableLoading(true);
      try {
        const resp = await postJSON<{ sellable_terminal_ids?: string[] }>("/buyer/bkk_sellable_terminals", {
          user_id: userId,
          to_keyword_id: toId,
          departure_date: depDate,
          locale: "en",
          currency: "THB",
        });
        if (cancelled) return;
        const ids = Array.isArray(resp?.sellable_terminal_ids) ? resp.sellable_terminal_ids : [];
        setBkkSellableIds(ids);
      } catch {
        if (cancelled) return;
        setBkkSellableIds([]);
      } finally {
        if (!cancelled) setBkkSellableLoading(false);
      }
    })();
    return () => { cancelled = true; };
  }, [pendingBangkokFrom]);

  // ─── send() ──────────────────────────────────────────────────────────────
  async function send(
    outgoing: string,
    opts?: { echoUser?: boolean; force?: boolean }
  ) {
    const t = String(outgoing || "").trim();
    if (!t) return;

    if (!opts?.force) {
      if (inFlightRef.current) return;
      inFlightRef.current = true;
    }

    const echoUser = opts?.echoUser !== false;
    const pendingAskSig = computeAskSig(stateRef.current.ask as any);
    dispatch({ type: "SEND_START", pendingAskSig, echoUserText: echoUser ? t : undefined });

    try {
      const env = await sendText({ endpoint, userId, text: t, state: stateRef.current.serverState });
      if (debug) console.log("[send OK]", t, env);
      dispatch({ type: "SEND_OK", env, userText: echoUser ? t : undefined, cachedChoice: stateRef.current.cachedChoice });
    } catch (e: any) {
      if (debug) console.error("[send FAIL]", e);
      dispatch({ type: "SEND_FAIL", userText: echoUser ? t : undefined, errorText: `Sorry — I couldn't do that. ${e?.message || e}` });
    } finally {
      if (!opts?.force) inFlightRef.current = false;
    }
  }

  // ─── Booking actions (cancel / refund / reset) ───────────────────────────
  const { doCancelReservation, doRefundOrCancel } = useBookingActions({
    endpoint,
    userId,
    stateRef,
    inFlightRef,
    dispatch,
    send,
  });

  // ─── Form submit ─────────────────────────────────────────────────────────
  function onSubmit(e: React.FormEvent) {
    e.preventDefault();
    const t = text;
    setText("");
    setComposerHint("");

    void send(t);
  }

  function cancelBkkFlow() {
    setBkkDestStep(false);
    setBkkDestHint("");
    setPendingBangkokFrom(false);
  }

  // ─── Derived render flags ─────────────────────────────────────────────────
  const askType      = String((state.ask as any)?.type  || "");
  const askField     = String((state.ask as any)?.field || "");
  const askPromptRaw = String((state.ask as any)?.prompt || "");
  const askPrompt    = cleanPrompt(askPromptRaw) || askPromptRaw;
  const askSig       = computeAskSig(state.ask as any);
  const collapseAskUI = Boolean(
    (state.loading || inFlightRef.current) && state.pendingAskSig && state.pendingAskSig === askSig
  );

  const showPassengerCard = askField === "passenger_details" && !state.reservation;
  const showDateQuick = askField === "departure_date" || askField === "date";
  const showFromQuick = askField === "from";
  const showToQuick   = askField === "to";
  const showPaxQuick  = askField === "pax";
  const showChoice =
    askType === "choice" &&
    Array.isArray((state.ask as any)?.options) &&
    (state.ask as any).options.length > 0;
  const showSeatmap = askType === "seatmap";

  useEffect(() => { if (!showDateQuick) setComposerHint(""); }, [showDateQuick]);

  // Bangkok is currently the only valid departure city.
  // Auto-trigger the terminal picker as soon as the backend asks for `from`,
  // so the user never sees a departure chips menu.
  // TODO: remove this effect (and restore QuickFromChips) when multi-city departures go live.
  useEffect(() => {
    if (!showFromQuick || bkkActive) return;
    const knownDest = pick(stateRef.current.serverState, DEST_KEYS);
    if (knownDest) {
      setBkkDestHint(knownDest);
      setPendingBangkokFrom(true);
    } else {
      setBkkDestStep(true);
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [showFromQuick]);

  const terminalDestName = bkkDestHint || pick(state.serverState, DEST_KEYS);
  const bkkActive = bkkDestStep || pendingBangkokFrom;

  // ─── Render ───────────────────────────────────────────────────────────────
  return (
    <div className="app">
      <div className="topbar">
        <div className="brand">
          <div className="logo">BX</div>
          <div>
            <div className="title">BusX Premium Buyer</div>
            <div className="muted" style={{ fontSize: 12 }}>session: {userId}</div>
          </div>
        </div>
        <div className="topActions">
          <button
            className="btn btnGhost"
            type="button"
            onClick={() => void send("reset", { echoUser: false })}
            disabled={state.loading || inFlightRef.current}
            title="Start over"
          >
            Reset
          </button>
        </div>
      </div>

      <div className="chat">
        {state.bubbles.map((m) => {
          const parsed = m.role === "bot" ? parseReservationCard(m.text) : null;
          if (parsed) {
            const passenger = state.lastPassenger || (state.reservation as any)?.passenger || undefined;
            return (
              <div key={m.id} className={`row ${m.role}`}>
                <div className="bubbleCard">
                  <ReservationCard
                    data={{ ...parsed, passenger }}
                    disabled={state.loading || inFlightRef.current}
                    onPay={() => void send("pay")}
                    onStatus={() => void send("status")}
                    onCancel={() => void doCancelReservation()}
                    onRefund={() => void doRefundOrCancel()}
                  />
                </div>
              </div>
            );
          }

          const st = m.role === "bot" ? parseStatusCard(m.text) : null;
          if (st) {
            return (
              <div key={m.id} className={`row ${m.role}`}>
                <div className="bubbleCard">
                  <StatusCard
                    data={st}
                    disabled={state.loading || inFlightRef.current}
                    onPay={() => void send("pay")}
                    onRefresh={() => void send("status")}
                  />
                </div>
              </div>
            );
          }

          return (
            <div key={m.id} className={`row ${m.role}`}>
              <div className="bubble">{m.text}</div>
            </div>
          );
        })}

        {/* ── Step 1 of 2: Destination-first — ask before showing terminal picker ── */}
        {bkkDestStep && !collapseAskUI && (
          <div className="row bot">
            <div className="bubbleCard">
              <div style={{ fontWeight: 700, marginBottom: 8 }}>
                Where are you heading?
              </div>
              <div className="muted" style={{ marginBottom: 10, fontSize: 13 }}>
                We'll show you the Bangkok terminal that best serves your route.
              </div>
              <QuickToChips
                disabled={state.loading || inFlightRef.current}
                onPick={(v) => {
                  if (v === "__OTHER__") return;
                  setBkkDestHint(v);
                  setBkkDestStep(false);
                  setPendingBangkokFrom(true);
                }}
              />
              <div style={{ marginTop: 10 }} className="muted">
                Or type your destination, then tap Bangkok in the departure chips.
              </div>
              <button
                type="button"
                className="btn btnGhost"
                style={{ marginTop: 8 }}
                onClick={cancelBkkFlow}
                disabled={state.loading || inFlightRef.current}
              >
                Back
              </button>
            </div>
          </div>
        )}

        {/* ── Step 2 of 2: Bangkok terminal picker ── */}
        {pendingBangkokFrom && !collapseAskUI && (
          <div className="row bot">
            <div className="bubbleCard">
              <BangkokTerminalPicker
                disabled={state.loading || inFlightRef.current}
                destinationName={terminalDestName}
                allowedTerminalIds={bkkSellableIds ?? undefined}
                loading={bkkSellableLoading}
                onPick={(terminalValue) => {
                  setPendingBangkokFrom(false);
                  setBkkDestHint("");
                  void send(terminalValue);
                }}
                onCancel={cancelBkkFlow}
              />
            </div>
          </div>
        )}

        {showChoice && !collapseAskUI && !bkkActive && (
          <div className="row bot">
            <div className="bubbleCard">
              {askField === "from" ? (
                <TerminalPickerCard
                  disabled={state.loading || inFlightRef.current}
                  title={(askPrompt || "Choose your departure terminal").trim()}
                  subtitle="Pick the specific station/terminal (not just the city)."
                  options={(state.ask as any).options || []}
                  onPick={(v, label) => {
                    if (isBangkokInput(String(label || v || ""))) {
                      const knownDest = pick(stateRef.current.serverState, DEST_KEYS);
                      if (knownDest) { setBkkDestHint(knownDest); setPendingBangkokFrom(true); }
                      else setBkkDestStep(true);
                      return;
                    }
                    void send(String(v));
                  }}
                />
              ) : (
                <ChoiceChips
                  disabled={state.loading || inFlightRef.current}
                  title={(askPrompt || "Choose from above").trim()}
                  options={(state.ask as any).options || []}
                  onPick={(v) => void send(String(v))}
                />
              )}
            </div>
          </div>
        )}

        {showToQuick && !collapseAskUI && (
          <div className="row bot">
            <div className="bubbleCard">
              <QuickToChips
                disabled={state.loading || inFlightRef.current}
                title={(askPrompt || "Where are you going?").trim()}
                onPick={(v) => {
                  if (v === "__OTHER__") return;
                  void send(String(v));
                }}
              />
              <div style={{ marginTop: 10 }} className="muted">
                Or type a city/terminal name.
              </div>
            </div>
          </div>
        )}

        {showPaxQuick && (
          <div className="row bot">
            <div className="bubbleCard">
              <PaxChips
                disabled={state.loading || inFlightRef.current}
                title={(askPrompt || "How many tickets?").trim()}
                onPick={(v) => void send(String(v))}
              />
            </div>
          </div>
        )}

        {showSeatmap && (
          <div className="row bot">
            <div className="bubbleCard">
              <SeatMapPicker
                disabled={state.loading || inFlightRef.current}
                title={(askPrompt || "Choose seats").trim()}
                seats={(state.ask as any).seats || []}
                pax={Number((state.ask as any).pax || 1)}
                selected={(state.ask as any).selected || []}
                onSubmit={(picked) => void send(picked.join(","))}
              />
            </div>
          </div>
        )}

        {showPassengerCard && (
          <div className="row bot">
            <div className="bubbleCard">
              <PassengerDetailsCard
                disabled={state.loading || inFlightRef.current}
                onSubmit={(payloadText) => {
                  try {
                    const obj = JSON.parse(payloadText);
                    const snap: PassengerSnap = {
                      title:     obj?.title || obj?.title_text || undefined,
                      gender:    obj?.passenger_gender || undefined,
                      firstName: obj?.first || obj?.first_name || obj?.firstName || undefined,
                      lastName:  obj?.last  || obj?.last_name  || obj?.lastName  || undefined,
                      email:     obj?.email || obj?.passenger_email || undefined,
                      phone:     obj?.phone || obj?.passenger_phone_number || undefined,
                    };
                    dispatch({ type: "SET_LAST_PASSENGER", passenger: snap });
                  } catch { /* ignore parse errors */ }
                  void send(payloadText, { echoUser: false });
                }}
              />
            </div>
          </div>
        )}

        {showDateQuick && !collapseAskUI && (
          <div className="row bot">
            <div className="bubbleCard">
              <div style={{ fontWeight: 700, marginBottom: 8 }}>What travel date?</div>
              <DateQuickChips
                disabled={state.loading || inFlightRef.current}
                onPick={(v) => { setComposerHint(""); void send(v); }}
                onOther={() => setComposerHint("Type a date like YYYY-MM-DD")}
              />
            </div>
          </div>
        )}

        {state.loading && (
          <div className="row bot">
            <div className="bubble"><TypingDots /></div>
          </div>
        )}

        <div ref={bottomRef} />
      </div>

      <div className="composer">
        <form className="composerInner" onSubmit={onSubmit}>
          <input
            type="text"
            value={text}
            onChange={(e) => setText(e.target.value)}
            placeholder={state.loading ? "" : composerHint || "Type here…"}
            disabled={state.loading || inFlightRef.current}
          />
          <button
            className="btn btnPrimary"
            type="submit"
            disabled={state.loading || inFlightRef.current || !text.trim()}
          >
            Send
          </button>
        </form>
      </div>
    </div>
  );
}
