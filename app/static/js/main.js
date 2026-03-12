import { chat } from "./api.js";
import { createStore, computeAskKey } from "./store.js";
import { createUI, $id } from "./ui.js";
import { renderDateAsk } from "./components/date.js";
import { renderPaxAsk } from "./components/pax.js";
import { renderQuickFrom, renderQuickTo } from "./components/quickPlaces.js";

const DEFAULT_ENDPOINT = "/buyer/chat";
const DEFAULT_USER_ID = "web-buyer-1";

const qs = new URLSearchParams(window.location.search);
const endpoint = (qs.get("endpoint") || DEFAULT_ENDPOINT).trim();
const userId = (qs.get("user_id") || DEFAULT_USER_ID).trim();

const store = createStore({ endpoint, userId });
const ui = createUI();

const textEl = $id("text");
const sendBtn = $id("sendBtn");
const resetBtn = $id("resetBtn");
const manageBtn = $id("manageBtn");
const datePickerEl = $id("datePicker");

// ---------------------------------------------------------------------------
// Composer modes (e.g., collect passenger details in the chat bar)
// ---------------------------------------------------------------------------
const passengerSteps = [
  { key: "first", label: "First name", placeholder: "First name" },
  { key: "last", label: "Surname", placeholder: "Surname" },
  { key: "email", label: "Email", placeholder: "Email (example: you@email.com)" },
  { key: "phone", label: "Phone", placeholder: "Phone (example: 0812345678)" },
];

function dateExampleISO(daysAhead = 1) {
  const d = new Date();
  d.setDate(d.getDate() + daysAhead);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

function normalizeThaiPhoneDraft(v) {
  // Live input helper (Thailand-focused):
  // - Strip spaces/dashes/etc.
  // - Convert +66 / 66xxxxxxxxx / 0066xxxxxxxxx -> 0xxxxxxxxx
  // - Keep only digits, limit to 10 (0xxxxxxxxx)
  let s = String(v ?? "");
  s = s.replace(/\D+/g, "");
  if (s.startsWith("0066")) s = "66" + s.slice(4);
  if (s.startsWith("66")) s = "0" + s.slice(2);
  if (s.length > 10) s = s.slice(0, 10);
  return s;
}

function startPassengerComposer(defaults = {}) {
  store.composerMode = {
    kind: "passenger",
    step: 0,
    data: {
      first: defaults.first || "",
      last: defaults.last || "",
      email: defaults.email || "",
      phone: defaults.phone || "",
      // keep existing backend defaults (optional fields)
      gender: defaults.gender || "M",
      title_id: defaults.title_id || "1",
    },
  };
  try { sendBtn.textContent = "Next"; } catch {}
  focusComposer(passengerSteps[0].placeholder);
  // Prompt first field explicitly in chat
  try { ui.addMessage("bot", `Please enter ${passengerSteps[0].label}.`); } catch {}

}

function stopComposerMode() {
  store.composerMode = null;
  try { sendBtn.textContent = "Send"; } catch {}
  focusComposer();
}

// Restore persisted state (refresh-safe)
if (store.serverState && Object.keys(store.serverState).length) {
  try { updateWizardFromServerState(store.serverState); } catch {}
  try { ui.renderSummary(store.wizard); } catch {}
  try { ui.setProgress(store.serverState); } catch {}
  try { updateManageButton(store.serverState); } catch {}

  // If we have a persisted ask, re-render it so the user can continue after refresh.
  if (store.ask) {
    try {
      renderAsk({ ask: store.ask, state: store.serverState, say: store.lastSay || "" }, (store.lastSay || ""));
    } catch {}
  }
}

async function _postJSON(url, payload) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload || {}),
  });
  const data = await r.json().catch(() => ({}));
  if (!r.ok) {
    const msg = data?.error || data?.message || `${r.status} ${r.statusText}`;
    throw new Error(msg);
  }
  return data;
}


async function maybeShowTicket(state) {
  try {
    const step = String(state?.step || "").toUpperCase();
    const bookingId = state?.reservation_id || state?.booking_id;
    if (!bookingId) return;
    if (step !== "PAID") return;

    // Avoid spamming: only show once per booking id per page session
    window.__shownTicketFor = window.__shownTicketFor || new Set();
    if (window.__shownTicketFor.has(String(bookingId))) return;

    window.__shownTicketFor.add(String(bookingId));
    const resp = await _postJSON("/buyer/get_tickets", { booking_id: bookingId, ticket_format: "json" });
    if (typeof ui.addTicketCard === "function") {
      ui.addTicketCard(resp, { bookingId });
    } else {
      ui.addMessage("bot", "Ticket is ready.");
    }
  } catch {
    // ignore
  }
}


function updateManageButton(state) {
  if (!manageBtn) return;
  const hasBooking = !!(state && typeof state === "object" && (state.reservation_id || state.booking_id));
  manageBtn.style.display = hasBooking ? "inline-flex" : "none";
}

// Cancel/Refund is accessed via the Manage menu (not a separate header button)

async function _softResetToStart(message) {
  try {
    if (typeof store.clear === "function") store.clear();
    else {
      store.serverState = {};
      store.renderedAskKeys.clear();
      try { store.uiState.dateManualEntry = false; } catch {}
    }
    if (message) ui.addMessage("bot", message);

    ui.setBusy(true, "Resetting…");
    const env = await chat({ endpoint: store.endpoint, userId: store.userId, text: "reset", state: {} });
    store.serverState = env.state ?? {};
    store.ask = env.ask ?? null;
    store.lastSay = env.say || "";
    updateWizardFromServerState(store.serverState);
    updateManageButton(store.serverState);
    try { updateManageButton(store.serverState); } catch {}
    if (typeof store.save === "function") store.save();
    ui.addMessage("bot", env.say || "Hi");
    renderAsk(env);
  } catch (e) {
    ui.addMessage("bot", `Couldn’t reset: ${e?.message || e}`);
  } finally {
    ui.setBusy(false);
    focusComposer();
  }
}


// Expose minimal hooks for UI widgets (reservation refresh, etc.)
window.__busxBuyer = {
  getState: () => store.serverState,
  setBusy: (on, label) => ui.setBusy(!!on, label || "Working…"),
  // sendText attached after definition
  sendText: null,
};

function isISODate(s) {
  return /^\d{4}-\d{2}-\d{2}$/.test(String(s || "").trim());
}

function isYYYYMMDD(s) {
  return /^\d{8}$/.test(String(s || "").trim());
}

function yyyymmddToISO(s) {
  const t = String(s || "").trim();
  if (!isYYYYMMDD(t)) return null;
  const yyyy = t.slice(0, 4);
  const mm = t.slice(4, 6);
  const dd = t.slice(6, 8);
  return `${yyyy}-${mm}-${dd}`;
}

function isPax(s) {
  const t = String(s || "").trim();
  if (!/^\d{1,2}$/.test(t)) return false;
  const n = parseInt(t, 10);
  return n >= 1 && n <= 20;
}

function guessBusyText(outgoingText) {
  const t = String(outgoingText || "").trim().toLowerCase();
  if (t === "reset") return "Resetting…";
  if (t === "pay") return "Preparing payment…";
  if (t === "reserve" || t === "confirm") return "Creating reservation…";

  // Build a "prospective" state assuming the outgoing text updates one field.
  const s = { ...(store.serverState || {}) };
  if (isISODate(outgoingText)) s.departure_date = String(outgoingText).trim();
  if (isPax(outgoingText)) s.pax = String(parseInt(String(outgoingText).trim(), 10));

  const step = String(s.step || "NEW").toUpperCase();
  const hasRoute = !!s.from_keyword_id && !!s.to_keyword_id;
  const hasDate = !!s.departure_date;
  const hasPax = !!s.pax;

  // Early steps: make the copy more helpful than "Working…"
  const hasFrom = !!s.from_keyword_id;
  const hasTo = !!s.to_keyword_id;

  // When collecting origins/destinations, the system typically calls stop keyword APIs.
  if (step === "NEW" && hasDate && !hasFrom) return "Looking for your best departure location";
  if (step === "NEW" && hasDate && hasFrom && !hasTo) return "Looking for your best destination";

  // Most common long call: trip search (routes) once we have from/to/date/pax.
  if (step === "NEW" && hasRoute && hasDate && hasPax) return "Searching routes…";
  if (step === "PICK_TRIP") return "Loading seats…";
  if (step === "PICK_SEATS") return "Holding seats…";
  if (step === "PAYMENT_PENDING") return "Checking payment…";

  return "Working…";
}

function focusComposer(placeholder) {
  try {
    if (typeof placeholder === "string" && placeholder.length) {
      textEl.setAttribute("placeholder", placeholder);
    }
    textEl.focus();
  } catch (_) {
    // ignore
  }
}

// ---------------------------------------------------------------------------
// Tripbar edit shortcuts (no reset): Route / Date / Pax
// ---------------------------------------------------------------------------
function wireTripbarEdits() {
  const btnRoute = document.getElementById("tbChangeRoute");
  const btnDate = document.getElementById("tbChangeDate");
  const btnPax = document.getElementById("tbChangePax");

  if (btnDate) {
    btnDate.addEventListener("click", () => {
      try {
        // Prefer native picker when available
        if (datePickerEl && datePickerEl.showPicker) datePickerEl.showPicker();
        else datePickerEl?.click?.();
      } catch {
        // ignore
      }
      try {
        store.uiState.dateManualEntry = true;
        if (typeof store.save === "function") store.save();
      } catch {}
      focusComposer(`Please type your date here (YYYY-MM-DD). Example: ${dateExampleISO(1)}`);
    });
  }

  if (btnPax) {
    btnPax.addEventListener("click", () => {
      // Render a quick pax picker bubble (local UI), user can still type.
      renderPaxAsk({
        ui,
        title: "How many passengers?",
        onPick: async (val) => {
          if (val === "__OTHER__") return focusComposer("Type passenger count (1-20)");
          await sendText(String(val));
        },
      });
      focusComposer("Type passenger count (1-20)");
    });
  }

  if (btnRoute) {
    btnRoute.addEventListener("click", () => {
      // Two quick bubbles: From then To. This keeps the user in-flow.
      renderQuickFrom({
        ui,
        title: "Change departure city",
        onPick: async (val) => {
          await sendText(String(val));
          renderQuickTo({
            ui,
            title: "Change destination city",
            onPick: async (val2) => {
              if (val2 === "__OTHER__") return focusComposer("Type destination city");
              await sendText(String(val2));
            },
          });
        },
      });
      focusComposer("Type city name");
    });
  }
}

function updateWizardFromServerState(state) {
  if (!state || typeof state !== "object") return;
  if (state.from_label) store.wizard.from = state.from_label;
  if (state.to_label) store.wizard.to = state.to_label;
  if (state.pax) store.wizard.pax = String(state.pax);
  if (state.departure_date) store.wizard.date = String(state.departure_date);

  // Selected trip summary (best-effort)
  try {
    const trip = state.selected_trip || null;
    if (trip && typeof trip === "object") {
      const get = (obj, path) => {
        let cur = obj;
        for (const p of path) {
          if (!cur || typeof cur !== "object") return null;
          cur = cur[p];
        }
        return cur;
      };

      const time =
        get(trip, ["trip_time"]) ||
        get(trip, ["departure_time"]) ||
        get(trip, ["departure", "time"]) ||
        get(trip, ["route", "departure", "time"]) ||
        null;

      const op =
        get(trip, ["operator", "name"]) ||
        get(trip, ["operator_name"]) ||
        get(trip, ["company_name"]) ||
        null;

      const tn = get(trip, ["trip_number"]) || get(trip, ["trip_no"]) || null;

      const parts = [];
      if (time) parts.push(String(time));
      if (op) parts.push(String(op));
      if (tn) parts.push(`#${String(tn)}`);
      store.wizard.trip = parts.length ? parts.join(" · ") : null;
    }
  } catch {
    // ignore
  }

  // Total price (best-effort)
  try {
    const co = state.checkout_response || null;
    const pay = co?.data?.order?.payment || null;
    const total = pay?.total_price;
    const cur = pay?.currency;
    store.wizard.total = total && cur ? `${total} ${cur}` : (total ? String(total) : store.wizard.total);
  } catch {
    // ignore
  }

  ui.renderSummary(store.wizard);
  try { ui.setProgress(state); } catch {}
  updateManageButton(state);
}

async function _sendToBackend(trimmed, { echoUser = true } = {}) {
  // Don't allow input while we're processing
  sendBtn.disabled = true;
  textEl.disabled = true;

  if (echoUser) ui.addMessage("user", trimmed);
  textEl.value = "";

  // Busy indicator: always use dancing dots only (no status text / skeleton bubbles)
  ui.setBusy(true, "");
  const statusHandle = null;

  try {
    const env = await chat({
      endpoint: store.endpoint,
      userId: store.userId,
      text: trimmed,
      state: store.serverState,
    });

    store.serverState = env.state ?? {};
    store.ask = env.ask ?? null;
    store.lastSay = env.say || "";
    updateWizardFromServerState(store.serverState);
    if (typeof store.save === "function") store.save();

    // No temporary status bubble to remove

    // If the server is returning an interactive ask (buttons/seatmap/etc.),
    // render a single BusX message that contains the prompt + UI, instead of
    // printing the prompt twice (once as say, once as the options card).
    const ask = env?.ask || null;
    const combinesWithAsk = !!ask && (
      ask.type === "seatmap" ||
      ask.type === "choice" ||
      ["from", "to", "departure_date", "date", "pax", "passenger_details"].includes(String(ask.field || ""))
    );

    if (!combinesWithAsk && env.say) ui.addMessage("bot", env.say);
    renderAsk(env, combinesWithAsk ? (env.say || "") : "");
    // Fallback: if backend indicates DETAILS step but did not send ask, start passenger collection
    if (String(env?.state?.step || "").toUpperCase() === "DETAILS" && (!env?.ask || String(env?.ask?.field||"") !== "passenger_details")) {
      if (!store.composerMode || store.composerMode.kind !== "passenger") {
        startPassengerComposer({});
      }
    }

    // If paid, fetch and show ticket card once.
    maybeShowTicket(store.serverState);
  } catch (e) {
    ui.addMessage("bot", `Error: ${e?.message || e}`);
  } finally {
    ui.setBusy(false);
    sendBtn.disabled = false;
    textEl.disabled = false;
    focusComposer();
  }
}

async function sendText(text) {
  const trimmed = String(text ?? "").trim();
  if (!trimmed) return;

  // If we're in a date ask and the user submitted a valid date, exit manual-entry mode.
  try {
    const askField = String(store?.ask?.field || "");
    const isDateAsk = askField === "date" || askField === "departure_date";
    if (isDateAsk) {
      if (isISODate(trimmed) || isYYYYMMDD(trimmed)) {
        store.uiState.dateManualEntry = false;
        if (typeof store.save === "function") store.save();
      }
    }
  } catch {
    // ignore
  }

  // Global commands should work even while collecting passenger details.
  // Otherwise users typing "reset" get their command captured as a field value.
  const cmd = trimmed.toLowerCase();
  if (cmd === "reset") {
    // Exit any composer mode and reset backend state.
    if (store.composerMode) stopComposerMode();
    await _sendToBackend("reset", { echoUser: true });
    return;
  }

  // Passenger details collection in the chat bar
  const mode = store.composerMode;
  if (mode && mode.kind === "passenger") {
    const stepDef = passengerSteps[mode.step] || null;
    if (!stepDef) {
      stopComposerMode();
      return;
    }

    // Record and show a labeled user line (clear but not verbose)
    mode.data[stepDef.key] = trimmed;
    ui.addMessage("user", `${stepDef.label}: ${trimmed}`);
    textEl.value = "";

    mode.step += 1;
    if (mode.step < passengerSteps.length) {
      // Prompt next field explicitly
      try { ui.addMessage("bot", `Please enter ${passengerSteps[mode.step].label}.`); } catch {}
      focusComposer(passengerSteps[mode.step].placeholder);
      return;
    }

    // Done: send JSON payload to backend without echoing another user message
    const payload = { ...mode.data };
    stopComposerMode();
    await _sendToBackend(JSON.stringify(payload), { echoUser: false });
    return;
  }

  await _sendToBackend(trimmed, { echoUser: true });
}


// Allow UI components to trigger commands without typing (Pay/Status/etc.)
window.__busxBuyer.sendText = (txt) => sendText(txt);
function renderAsk(env, promptOverride = "") {
  const ask = env?.ask || null;
  const askKey = computeAskKey(env);

  if (store.renderedAskKeys.has(askKey)) return;
  store.renderedAskKeys.add(askKey);

  if (!ask) return;

  // If we're leaving the date ask, ensure manual-entry mode is cleared.
  try {
    const f = String(ask.field || "");
    const isDateAsk = f === "date" || f === "departure_date";
    if (!isDateAsk) store.uiState.dateManualEntry = false;
  } catch {
    // ignore
  }

  if (ask.type === "seatmap") {
    ui.addSeatMapBubble({
      title: (promptOverride || ask.prompt || "Choose seats").trim(),
      seats: ask.seats || [],
      pax: ask.pax || 1,
      selected: ask.selected || [],
      onSubmit: async (picked) => {
        await sendText(
          (Array.isArray(picked) ? picked.join(",") : String(picked || "")).trim()
        );
      },
    });
    return;
  }

  if (ask.type === "choice") {
    const options = (ask.options || []).map((o) => ({
      value: o.value,
      label: o.label,
      primary: false,
    }));
    ui.addButtonsBubble({
      title: (promptOverride || ask.prompt || "Choose one").trim(),
      options,
      onPick: async (opt) => sendText(opt.value),
    });
    return;
  }

  const field = String(ask.field || "");

  if (field === "passenger_details") {
    // Collect passenger details with an in-chat form card (premium UX)
    const title = (promptOverride || ask.prompt || "Before I create your reservation, please enter passenger details.").trim();

    // Ensure we are not in step-by-step composer mode.
    try { if (store.composerMode) stopComposerMode(); } catch {}

    ui.addPassengerDetailsBubble({
      title,
      defaults: (ask.defaults || {}),
      onSubmit: async (payload) => {
        // Optional: show a compact confirmation in the chat stream
        try {
          const safePhone = String(payload.phone || "").trim();
          ui.addMessage("user", `Passenger: ${payload.first} ${payload.last}${safePhone ? " • " + safePhone : ""}`);
        } catch {}
        // Backend expects passenger details as JSON string
        await _sendToBackend(JSON.stringify(payload), { echoUser: false });
      },
    });
    return;
  }



  // Some backends use "departure_date" while others use "date".
  // Support both so the composer hint always updates.
  if (field === "departure_date" || field === "date") {
    renderDateAsk({
      ui,
      datePickerEl,
      title: (promptOverride || ask.prompt || "Pick a travel date").trim(),
      onOther: () => {
        store.uiState.dateManualEntry = true;
        if (typeof store.save === "function") store.save();
        focusComposer(`Please type your date here (YYYY-MM-DD). Example: ${dateExampleISO(1)}`);
      },
      onPick: async (_raw, iso) => {
        store.wizard.date = iso;
        ui.renderSummary(store.wizard);
        store.uiState.dateManualEntry = false;
        if (typeof store.save === "function") store.save();
        await sendText(iso);
      },
    });

    // Default placeholder should remain neutral unless the user chose "Other date…".
    if (store.uiState.dateManualEntry) {
      focusComposer(`Please type your date here (YYYY-MM-DD). Example: ${dateExampleISO(1)}`);
    } else {
      focusComposer("Type here…");
    }
    return;
  }

  if (field === "to") {
    renderQuickTo({
      ui,
      title: (promptOverride || ask.prompt || "Where are you going?").trim(),
      onPick: async (v) => {
        if (v === "__OTHER__") {
          // IMPORTANT: role should be "bot" to match your CSS ("assistant" likely won't style)
          ui.addMessage("bot", "Type your destination (city/terminal) below.");
          focusComposer("Type destination…");
          return;
        }
        store.wizard.to = v;
        ui.renderSummary(store.wizard);
        await sendText(v);
      },
    });
    return;
  }

  if (field === "from") {
    renderQuickFrom({
      ui,
      title: (promptOverride || ask.prompt || "Where are you departing from?").trim(),
      onPick: async (v) => {
        store.wizard.from = v;
        ui.renderSummary(store.wizard);
        await sendText(v);
      },
    });
    return;
  }

  if (field === "pax") {
    renderPaxAsk({
      ui,
      title: (promptOverride || ask.prompt || "How many tickets?").trim(),
      onPick: async (v) => {
        store.wizard.pax = v;
        ui.renderSummary(store.wizard);
        await sendText(v);
      },
    });
    return;
  }

  // passenger_details handled above
}

// Wire once
wireTripbarEdits();

sendBtn.addEventListener("click", () => sendText(textEl.value));

textEl.addEventListener("keydown", (e) => {
  if (e.key === "Enter") {
    e.preventDefault();
    sendText(textEl.value);
  }
});

// Live auto-formatting for passenger phone input (keeps it customer-friendly)
textEl.addEventListener("input", () => {
  const mode = store.composerMode;
  if (!mode || mode.kind !== "passenger") return;
  const stepDef = passengerSteps[mode.step] || null;
  if (!stepDef || stepDef.key !== "phone") return;

  const before = textEl.value;
  const after = normalizeThaiPhoneDraft(before);
  if (after !== before) {
    const pos = textEl.selectionStart;
    textEl.value = after;
    // keep caret near the end (good enough for this simple formatter)
    try { textEl.setSelectionRange(after.length, after.length); } catch {}
  }
});

resetBtn.addEventListener("click", async () => {
  // Best-effort: release held seats before resetting
  try {
    const s = store.serverState || {};
    if (s.selected_fare_ref_id && Array.isArray(s.seat_event_ids) && s.seat_event_ids.length) {
      await _postJSON("/buyer/unmark_seats", { state: s });
    }
  } catch {}

  if (typeof store.clear === "function") store.clear();
  else {
    store.serverState = {};
    store.renderedAskKeys.clear();
  }
  ui.addMessage("bot", "Resetting…");
  await sendText("reset");
});



// Manage booking (ticket actions)
async function cancelOrRefundFlow(bookingId) {
  try {
    ui.setBusy(true, "Loading…");
    const details = await _postJSON("/buyer/reservation_details", { state: store.serverState, booking_id: String(bookingId) });

    const pay = details?.data?.order?.payment || null;
    const payStatus = String(pay?.payment_status || pay?.status || "").trim().toUpperCase();

    const reservations = details?.data?.reservations || [];
    const first = Array.isArray(reservations) ? reservations[0] : null;
    const gtn = first?.global_ticket_number || details?.data?.global_ticket_number || null;

    ui.setBusy(false);

    // If ticket exists or payment is paid: refund flow
    if (gtn && (payStatus === "Y" || payStatus === "PAID" || payStatus === "SUCCESS")) {
      const req = await _postJSON("/buyer/request_refund", { global_ticket_number: String(gtn) });
      const row = Array.isArray(req?.data) ? req.data[0] : (req?.data || req);
      const allow = String(row?.allow_refund || "").trim().toUpperCase();
      const refundRefId = row?.refund_ref_id || null;
      const p = row?.payment || {};
      const ticketPrice = p?.ticket_price;
      const fee = p?.refund_fee;
      const refundAmount = p?.refund_amount;
      const currency = p?.currency;

      if (allow !== "Y" || !refundRefId) {
        ui.addMessage("bot", "Refund isn’t available for this ticket.");
        return;
      }

      const breakdown = [
        (refundAmount != null ? `Refund: ${refundAmount}${currency ? " " + currency : ""}` : null),
        (fee != null ? `Fee: ${fee}${currency ? " " + currency : ""}` : null),
        (ticketPrice != null ? `Ticket: ${ticketPrice}${currency ? " " + currency : ""}` : null),
      ].filter(Boolean).join(" · ");

      ui.addButtonsBubble({
        title: `Refund this ticket?${breakdown ? "\n" + breakdown : ""}`,
        options: [
          { value: "keep", label: "Keep ticket", primary: true },
          { value: "refund", label: "Request refund", danger: true },
        ],
        onPick: async (opt) => {
          if (opt.value !== "refund") return;
          ui.setBusy(true, "Requesting refund…");
          try {
            const res = await _postJSON("/buyer/create_refund", { refund_ref_id: String(refundRefId) });
            const ok = res?.success === true;
            ui.addMessage("bot", ok ? "✅ Refund requested." : "Refund request sent.");
            await _softResetToStart();
          } catch (e) {
            ui.addMessage("bot", `Refund failed: ${e?.message || e}`);
          } finally {
            ui.setBusy(false);
          }
        },
      });
      return;
    }

    // Otherwise: cancel reservation (release seats)
    ui.addButtonsBubble({
      title: "Cancel this reservation and release the seats?",
      options: [
        { value: "keep", label: "Keep reservation", primary: true },
        { value: "cancel", label: "Cancel reservation", danger: true },
      ],
      onPick: async (opt) => {
        if (opt.value !== "cancel") return;
        ui.setBusy(true, "Cancelling…");
        try {
          const res = await _postJSON("/buyer/cancel_reservation", { state: store.serverState, booking_id: String(bookingId) });
          const ok = res?.success === true;
          ui.addMessage("bot", ok ? "✅ Reservation cancelled." : "Reservation cancellation sent.");
          await _softResetToStart();
        } catch (e) {
          ui.addMessage("bot", `Cancel failed: ${e?.message || e}`);
        } finally {
          ui.setBusy(false);
        }
      },
    });
  } catch (e) {
    ui.setBusy(false);
    ui.addMessage("bot", `Couldn’t load reservation: ${e?.message || e}`);
  }
}

if (manageBtn) {
  manageBtn.addEventListener("click", async () => {
    const state = store.serverState || {};
    const bookingId = state.reservation_id || state.booking_id;
    if (!bookingId) return;

    ui.addButtonsBubble({
      title: "Manage booking",
      options: [
        { value: "view_ticket", label: "View ticket", primary: true },
        { value: "open_ended", label: "Make open-ended", primary: false },
        { value: "change_date", label: "Change travel date", primary: false },
        { value: "cancel_refund", label: "Cancel / Refund", danger: true },
      ],
      onPick: async (opt) => {
        if (opt.value === "cancel_refund") {
          await cancelOrRefundFlow(bookingId);
          return;
        }
        if (opt.value === "view_ticket") {
          const resp = await _postJSON("/buyer/get_tickets", { booking_id: bookingId, ticket_format: "json" });
          if (typeof ui.addTicketCard === "function") ui.addTicketCard(resp, { bookingId });
          return;
        }
        if (opt.value === "open_ended") {
          ui.setBusy(true, "Requesting open-ended…");
          const resp = await _postJSON("/buyer/manage_open_ended", { booking_id: bookingId, state });
          ui.setBusy(false);
          if (typeof ui.addManageResultCard === "function") ui.addManageResultCard("open_ended", resp);
          else ui.addMessage("bot", JSON.stringify(resp, null, 2));
          return;
        }
        if (opt.value === "change_date") {
          // Ask user for a new date then show trip choices for that date
          renderDateAsk({
            ui,
            datePickerEl,
            title: "Pick a new travel date",
            onPick: async (_raw, iso) => {
              ui.setBusy(true, "Searching trips…");
              const tripsResp = await _postJSON("/buyer/search_trips", {
                from_keyword_id: state.from_keyword_id,
                to_keyword_id: state.to_keyword_id,
                departure_date: iso,
                pax: state.pax || 1,
                currency: state.currency || "THB",
              });
              ui.setBusy(false);
              const trips = tripsResp?.data?.trips || tripsResp?.data || tripsResp?.trips || [];
              const opts = [];
              for (const t of (Array.isArray(trips) ? trips : [])) {
                const fare = t?.fare_ref_id || t?.fareRefId || t?.fare_ref || null;
                if (!fare) continue;
                const dep = t?.departure_time || t?.depart_time || t?.departure_datetime || "";
                const arr = t?.arrival_time || t?.arrive_time || "";
                const op = t?.carrier_name || t?.carrier || t?.operator_name || "";
                const price = t?.price?.total_price || t?.total_price || t?.price || "";
                const cur = t?.price?.currency || t?.currency || "";
                const label = [dep && `Dep ${dep}`, arr && `Arr ${arr}`, op, (price ? `${price} ${cur}`.trim() : "")].filter(Boolean).join(" · ");
                opts.push({ value: String(fare), label: label || String(fare), primary: false });
              }
              if (!opts.length) {
                ui.addMessage("bot", "No trips found for that date.");
                return;
              }
              ui.addButtonsBubble({
                title: "Pick a new trip",
                options: opts.slice(0, 12),
                onPick: async (pick) => {
                  ui.setBusy(true, "Rebooking…");
                  const resp = await _postJSON("/buyer/manage_set_travel_date", {
                    booking_id: bookingId,
                    new_fare_ref_id: pick.value,
                    state,
                  });
                  ui.setBusy(false);
                  if (typeof ui.addManageResultCard === "function") ui.addManageResultCard("set_travel_date", resp);
                  else ui.addMessage("bot", JSON.stringify(resp, null, 2));
                },
              });
            },
          });
        }
      },
    });
  });
}

// Cancel/Refund is handled inside the Manage menu.

// Boot
(async () => {
  // If we restored state from storage, don't force reset.
  if (store.serverState && Object.keys(store.serverState).length) {
    ui.setBusy(false);
    return;
  }
  ui.setBusy(true, "Connecting…");
  try {
    const env = await chat({
      endpoint: store.endpoint,
      userId: store.userId,
      text: "reset",
      state: {},
    });

    store.serverState = env.state ?? {};
    store.ask = env.ask ?? null;
    store.lastSay = env.say || "";

    updateWizardFromServerState(store.serverState);
    if (typeof store.save === "function") store.save();

    ui.addMessage("bot", env.say || "Hi");
    renderAsk(env);
  } catch (e) {
    ui.addMessage("bot", `Couldn’t connect: ${e?.message || e}`);
  } finally {
    ui.setBusy(false);
    focusComposer();
  }
})();