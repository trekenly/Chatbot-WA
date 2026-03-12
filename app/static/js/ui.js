export function $id(id) {
  return document.getElementById(id);
}

export function createUI() {
  const chatEl = $id("chat");
  const busyPill = $id("busyPill");
  const busyText = $id("busyText");
  const sumFrom = $id("sumFrom");
  const sumTo = $id("sumTo");
  const sumPax = $id("sumPax");
  const progressDots = $id("progressDots");
  const progressDotEls = progressDots ? Array.from(progressDots.querySelectorAll(".dot")) : [];

  // Header trip line (date • from → to)
  const htDate = $id("htDate");
  const htRoute = $id("htRoute");

  // Sticky trip summary bar (above composer)
  const tripbar = $id("tripbar");
  const tbRoute = $id("tbRoute");
  const tbDate = $id("tbDate");
  const tbPax = $id("tbPax");
  const tbTrip = $id("tbTrip");
  const tbTotal = $id("tbTotal");

  function scrollToBottom() {
    chatEl.scrollTop = chatEl.scrollHeight;
  }

  function _nowHM() {
    try {
      const d = new Date();
      return d.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
    } catch {
      return "";
    }
  }

// -------------------------------------------------------------------------
// Premium traveler summary formatting (Reservation created / payment expiry)
// -------------------------------------------------------------------------
const _countdownTimers = new Set();

function _escapeHtml(v) {
  return String(v ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  // Auto-refresh payment status (polite: every ~30s) while pending and not expired
  const cards = container.querySelectorAll(".travsum");
  cards.forEach((card) => {
    if (card.__autoPayTimer) return;

    const statusEl = card.querySelector(".travsum-status");
    const st = String(statusEl?.textContent || "").trim().toLowerCase();

    const cd = card.querySelector(".travsum-countdown");
    const expiresAt = cd?.getAttribute("data-expires") || "";

    if (!expiresAt) return;
    if (st === "y" || st === "paid" || st === "success") return;

    let tries = 0;

    const tick = async () => {
      try {
        // Stop if removed from DOM
        if (!card.isConnected) {
          clearInterval(card.__autoPayTimer);
          card.__autoPayTimer = null;
          return;
        }

        // Stop if already paid
        const cur = String(statusEl?.textContent || "").trim().toLowerCase();
        if (cur === "y" || cur === "paid" || cur === "success") {
          clearInterval(card.__autoPayTimer);
          card.__autoPayTimer = null;
          return;
        }

        // Stop if expired
        const exp = new Date(expiresAt);
        if (!isNaN(exp.getTime()) && Date.now() > exp.getTime()) {
          clearInterval(card.__autoPayTimer);
          card.__autoPayTimer = null;
          return;
        }

        // Keep attempts bounded
        tries += 1;
        if (tries > 40) {
          clearInterval(card.__autoPayTimer);
          card.__autoPayTimer = null;
          return;
        }

        const bookingId = card.getAttribute("data-booking-id") || "";
        if (!bookingId) return;

        const state = window.__busxBuyer?.getState?.() || {};
        const details = await _postJSON("/buyer/reservation_details", { state, booking_id: bookingId });

        const pay = details?.data?.order?.payment || null;
        const payStatus = pay?.payment_status || pay?.status || null;
        const expiresNew = pay?.expires_at || pay?.expire_at || null;
        const total = pay?.total_price || null;
        const curcy = pay?.currency || null;
        const paycode = details?.data?.order?.paycode || null;

        if (statusEl) statusEl.textContent = payStatus ? String(payStatus) : statusEl.textContent;

        const amountRow = card.querySelector("[data-field='amount']");
        if (amountRow && total) amountRow.textContent = curcy ? `${total} ${curcy}` : String(total);

        const pcRow = card.querySelector("[data-field='paycode']");
        if (pcRow && paycode) pcRow.textContent = String(paycode);

        const payref = card.querySelector("[data-field='payref']");
        if (payref && paycode) payref.textContent = String(paycode);

        const countdown = card.querySelector(".travsum-countdown");
        if (countdown && (expiresNew || expiresAt)) {
          countdown.setAttribute("data-expires", String(expiresNew || expiresAt));
          _refreshCountdowns();
        }

        const st2 = String(statusEl?.textContent || "").trim().toLowerCase();
        if (st2 === "y" || st2 === "paid" || st2 === "success") {
          clearInterval(card.__autoPayTimer);
          card.__autoPayTimer = null;
        }
      } catch {
        // silent
      }
    };

    // First tick after a short delay
    setTimeout(tick, 2000);
    card.__autoPayTimer = setInterval(tick, 30000);
  });

}

function _safeDateFromAny(v) {
  const s = String(v ?? "").trim();
  if (!s) return null;
  const d = new Date(s);
  return isNaN(d.getTime()) ? null : d;
}

function _formatLocalTime(dt) {
  try {
    return new Intl.DateTimeFormat(undefined, {
      hour: "numeric",
      minute: "2-digit",
    }).format(dt);
  } catch {
    const hh = String(dt.getHours()).padStart(2, "0");
    const mm = String(dt.getMinutes()).padStart(2, "0");
    return `${hh}:${mm}`;
  }
}

function _formatLocalDateTime(dt) {
  try {
    return new Intl.DateTimeFormat(undefined, {
      year: "numeric",
      month: "short",
      day: "2-digit",
      hour: "numeric",
      minute: "2-digit",
    }).format(dt);
  } catch {
    return dt.toLocaleString();
  }
}

function _relativeCountdown(dt) {
  const now = Date.now();
  const diffMs = dt.getTime() - now;
  const diffMin = Math.ceil(diffMs / 60000);
  if (diffMin <= 0) return "Expired";
  if (diffMin === 1) return "Expires in 1 min";
  if (diffMin < 60) return `Expires in ${diffMin} min`;
  const hrs = Math.floor(diffMin / 60);
  const mins = diffMin % 60;
  if (mins === 0) return `Expires in ${hrs} hr`;
  return `Expires in ${hrs} hr ${mins} min`;
}

function _relativePayWindow(dt) {
  const now = Date.now();
  const diffMs = dt.getTime() - now;
  const diffMin = Math.ceil(diffMs / 60000);
  if (diffMin <= 0) return "Payment expired";
  if (diffMin === 1) return "You have 1 min to pay";
  if (diffMin < 60) return `You have ${diffMin} min to pay`;
  const hrs = Math.floor(diffMin / 60);
  const mins = diffMin % 60;
  if (mins === 0) return `You have ${hrs} hr to pay`;
  return `You have ${hrs} hr ${mins} min to pay`;
}

function _installCountdown(el, expiresIso) {
  const dt = _safeDateFromAny(expiresIso);
  if (!dt || !el) return;

  const isPayTimer = el.classList?.contains("travsum-paytimer");

  const update = () => {
    el.textContent = isPayTimer ? _relativePayWindow(dt) : _relativeCountdown(dt);
    if (el.textContent === "Expired" || el.textContent === "Payment expired") {
      if (el.__timer) {
        clearInterval(el.__timer);
        _countdownTimers.delete(el.__timer);
        el.__timer = null;
      }
    }
  };
  update();
  if (el.__timer) return;
  const t = setInterval(update, 30000);
  el.__timer = t;
  _countdownTimers.add(t);
}

function _refreshCountdowns(root = document) {
  try {
    const els = root.querySelectorAll?.(".travsum-countdown[data-expires], .travsum-paytimer[data-expires]") || [];
    els.forEach((el) => {
      const ex = el.getAttribute("data-expires") || "";
      _installCountdown(el, ex);
    });
  } catch {
    // ignore
  }
}

function _copyToClipboard(text) {
  const t = String(text ?? "").trim();
  if (!t) return Promise.resolve(false);
  // Modern
  if (navigator.clipboard && navigator.clipboard.writeText) {
    return navigator.clipboard.writeText(t).then(() => true).catch(() => false);
  }
  // Fallback
  try {
    const ta = document.createElement("textarea");
    ta.value = t;
    ta.setAttribute("readonly", "");
    ta.style.position = "fixed";
    ta.style.left = "-10000px";
    ta.style.top = "-10000px";
    document.body.appendChild(ta);
    ta.select();
    const ok = document.execCommand("copy");
    ta.remove();
    return Promise.resolve(!!ok);
  } catch {
    return Promise.resolve(false);
  }
}

function _wireCopyButtons(container) {
  if (!container || !container.querySelectorAll) return;
  const btns = container.querySelectorAll(".copyBtn");
  btns.forEach((btn) => {
    if (btn.__wired) return;
    btn.__wired = true;
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const val = btn.getAttribute("data-copy") || "";
      const ok = await _copyToClipboard(val);
      const old = btn.getAttribute("data-label") || btn.textContent;
      btn.setAttribute("data-label", old);

      // Premium micro-feedback (no layout shift)
      btn.classList.toggle("copied", !!ok);
      btn.textContent = ok ? "Copied ✓" : "Copy";

      clearTimeout(btn.__copiedTimer);
      btn.__copiedTimer = setTimeout(() => {
        btn.textContent = old;
        btn.classList.remove("copied");
      }, 1500);
    });
  });
}

async function _postJSON(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body || {}),
  });
  const j = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(j?.error || `HTTP ${r.status}`);
  return j;
}

function _wireReservationButtons(container) {
  if (!container || !container.querySelectorAll) return;

  const checkBtns = container.querySelectorAll(".payCheckBtn");
  checkBtns.forEach((btn) => {
    if (btn.__wired) return;
    btn.__wired = true;
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();

      const card = btn.closest(".travsum");
      const bookingId = card?.getAttribute("data-booking-id") || "";
      if (!bookingId) return;

      try {
        window.__busxBuyer?.setBusy?.(true, "Checking payment…");
        btn.disabled = true;
        const state = window.__busxBuyer?.getState?.() || {};
        const details = await _postJSON("/buyer/reservation_details", { state, booking_id: bookingId });

        const pay = details?.data?.order?.payment || null;
        const payStatus = pay?.payment_status || pay?.status || null;
        const expiresAt = pay?.expires_at || pay?.expire_at || null;
        const total = pay?.total_price || null;
        const cur = pay?.currency || null;
        const paycode = details?.data?.order?.paycode || null;

        const statusEl = card?.querySelector(".travsum-status");
        if (statusEl) statusEl.textContent = payStatus ? String(payStatus) : "—";

        const amountRow = card?.querySelector("[data-field='amount']");
        if (amountRow && total) amountRow.textContent = cur ? `${total} ${cur}` : String(total);

        const pcRow = card?.querySelector("[data-field='paycode']");
        if (pcRow && paycode) pcRow.textContent = String(paycode);

        const countdown = card?.querySelector(".travsum-countdown");
        if (countdown && expiresAt) {
          countdown.setAttribute("data-expires", String(expiresAt));
          _refreshCountdowns();
        }
      } catch (_) {
        // Keep silent; user can retry.
      } finally {
        btn.disabled = false;
        window.__busxBuyer?.setBusy?.(false);
      }
    });
  });


  const cmdPayBtns = container.querySelectorAll(".cmdPayBtn");
  cmdPayBtns.forEach((btn) => {
    if (btn.__wired) return;
    btn.__wired = true;
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const send = window.__busxBuyer?.sendText;
      if (typeof send === "function") send("pay");
    });
  });

  const cmdStatusBtns = container.querySelectorAll(".cmdStatusBtn");
  cmdStatusBtns.forEach((btn) => {
    if (btn.__wired) return;
    btn.__wired = true;
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const send = window.__busxBuyer?.sendText;
      if (typeof send === "function") send("status");
    });
  });

  const copyAllBtns = container.querySelectorAll(".copyAllBtn");
  copyAllBtns.forEach((btn) => {
    if (btn.__wired) return;
    btn.__wired = true;
    btn.addEventListener("click", async (e) => {
      e.preventDefault();
      e.stopPropagation();
      const card = btn.closest(".travsum");
      const bookingId = card?.getAttribute("data-booking-id") || "";
      const paycode = card?.querySelector("[data-field='paycode']")?.textContent?.trim() || "";
      const amount = card?.querySelector("[data-field='amount']")?.textContent?.trim() || "";
      const payBy = card?.querySelector("[data-field='payby']")?.textContent?.trim() || "";
      const parts = [];
      if (bookingId) parts.push(`Booking ID: ${bookingId}`);
      if (paycode) parts.push(`Payment code: ${paycode}`);
      if (amount) parts.push(`Amount: ${amount}`);
      if (payBy) parts.push(`Pay by: ${payBy}`);
      const ok = await _copyToClipboard(parts.join("\n"));
      const old = btn.textContent;
      btn.textContent = ok ? "Copied" : "Copy";
      setTimeout(() => (btn.textContent = old), 900);
    });
  });
}

function _formatTravelerSummary(rawText) {
  const text = String(rawText ?? "");
  const looksLikeSummary =
    /Reservation created\./i.test(text) ||
    /^amount:\s*/im.test(text) ||
    /^expires_at:\s*/im.test(text);
  if (!looksLikeSummary) return null;

  const lines = text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

  const kv = {};
  for (const line of lines) {
    const m = line.match(/^([a-zA-Z_ ]+):\s*(.+)$/);
    if (m) {
      const key = m[1].trim().toLowerCase().replaceAll(" ", "_");
      kv[key] = m[2].trim();
    }
  }

  const selectedSeatsLine = lines.find((l) => /^Selected seats:/i.test(l));
  const seatsHeldLine = lines.find((l) => /^Seats held:/i.test(l));
  const reservationCreatedLine = lines.find((l) => /^Reservation created\./i.test(l));

  const amount = kv.amount;
  const expiresIso = kv.expires_at || kv.expires;
  const expiresDt = _safeDateFromAny(expiresIso);

  const payByNice = expiresDt ? _formatLocalTime(expiresDt) : null;
  const payByFull = expiresDt ? _formatLocalDateTime(expiresDt) : null;

  const seatValue =
    (selectedSeatsLine && selectedSeatsLine.replace(/^Selected seats:\s*/i, "")) ||
    kv.selected_seats ||
    null;

  const nextLine = lines.find((l) => /^Next:/i.test(l));

  const reservationId = kv.reservation_id;
  const orderRef = kv.order_ref_id;
  const paycode = kv.paycode || kv.payment_code || kv.paymentcode || kv.pay_code;
  const paymentStatus = kv.payment_status || kv.status || null;
  const seatEventIds =
    (seatsHeldLine && seatsHeldLine.match(/seat_event_id\(s\):\s*([^\)]+)\)/i)?.[1]?.trim()) ||
    null;

  const esc = _escapeHtml;
  const fmtNext = (s) => esc(String(s||"")).replace(/\*\*([^*]+)\*\*/g, "<strong>$1</strong>");

  const title = reservationCreatedLine
    ? "✅ <strong>Reservation created</strong>"
    : "✅ <strong>Trip confirmed</strong>";

  const rows = [];
  if (reservationId) rows.push({ label: "Booking ID", value: reservationId, copy: reservationId, field: "booking" });
  // Payment code shown in main card only when present; otherwise we fall back to order ref in payment line.
  if (paycode) rows.push({ label: "Payment code", value: paycode, copy: paycode, field: "paycode" });
  if (seatValue) rows.push({ label: "Seat", value: seatValue, field: "seat" });
  if (amount) rows.push({ label: "Amount", value: amount, field: "amount" });
  if (payByNice) rows.push({ label: "Pay by", value: `${payByNice}`, field: "payby" });
  if (paymentStatus) rows.push({ label: "Status", value: paymentStatus, field: "status" });

  const details = [];
  if (orderRef) details.push(`Order Ref: ${orderRef}`);
  if (paycode) details.push(`Paycode: ${paycode}`);
  if (seatEventIds) details.push(`Seat hold ref: ${seatEventIds}`);

  const payRefLabel = paycode ? "Payment code" : "Order Ref";
  const payRefValue = paycode || orderRef || "";

  const html = `
    <div class="travsum" data-booking-id="${esc(reservationId || "")}">
      <div class="travsum-head">
        <div class="travsum-title">${title}</div>
        ${expiresIso ? `<span class="travsum-countdown mini" data-expires="${esc(expiresIso)}"></span>` : ``}
      </div>

      ${expiresIso ? `<div class="travsum-paytimer" data-expires="${esc(expiresIso)}"></div>` : ``}

      ${rows.length ? `
        <div class="travsum-rows">
          ${rows.map(r => `
            <div class="travsum-row" data-row="${esc(r.field || "")}">
              <div class="travsum-label">${esc(r.label)}</div>
              <div class="travsum-value">
                <span class="travsum-val"><strong${r.field ? ` data-field="${esc(r.field)}"` : ``}${r.label === "Status" ? " class=\"travsum-status\"" : ""}>${esc(r.value)}</strong></span>
                ${r.copy ? `<button class="copyBtn" type="button" data-copy="${esc(r.copy)}">Copy</button>` : ``}
              </div>
            </div>
          `).join("")}
        </div>
      ` : ""}

      ${(paycode || orderRef) ? `
        <div class="travsum-paycompact">
          <div class="travsum-payref">
            <div class="travsum-label">${esc(payRefLabel)}</div>
            <div class="travsum-payref-val"><strong data-field="payref">${esc(payRefValue)}</strong></div>
          </div>
          <div class="travsum-payactions">
            <button class="copyAllBtn" type="button">Copy all</button>
            <button class="payCheckBtn" type="button">Check</button>
            <button class="cmdPayBtn" type="button" title="Start payment">Pay</button>
            <button class="cmdStatusBtn" type="button" title="Check status">Status</button>
          </div>
        </div>
      ` : ""}

      ${nextLine ? `
        <div class="travsum-nextmini">
          <span class="travsum-nextmini-k">Next:</span>
          <span class="travsum-nextmini-v">${fmtNext(nextLine.replace(/^Next:\s*/i, ""))}</span>
        </div>
      ` : ""}

      ${details.length ? `
        <details class="travsum-details">
          <summary>Details</summary>
          <div class="travsum-details-body">
            ${details.map(d => `<div>${esc(d)}</div>`).join("")}
          </div>
        </details>
      ` : ""}
    </div>
  `;



// -------------------------------------------------------------------------
// Ticket + Manage booking cards
// -------------------------------------------------------------------------

function addTicketCard(ticketResp, { bookingId } = {}) {
  const bubble = addMessage("bot", ""); // placeholder
  const inner = bubble.querySelector(".bubbleInner");
  if (!inner) return bubble;

  const ok = ticketResp && (ticketResp.success === true || ticketResp.success === "true");
  const data = ticketResp?.data || ticketResp?.data?.data || ticketResp?.data;

  // Expected shape (spec example): data.departure[0].ticket_data.e_ticket.ticket_list[]
  let tickets = [];
  let bookingUrl = "";
  try {
    const dep0 = (data?.departure && data.departure[0]) ? data.departure[0] : null;
    const et = dep0?.ticket_data?.e_ticket || null;
    bookingUrl = et?.ticket_url || "";
    const list = et?.ticket_list || [];
    if (Array.isArray(list)) {
      tickets = list.map((t) => ({
        gtn: t?.global_ticket_number || "",
        url: t?.ticket_url || "",
      })).filter((x) => x.gtn || x.url);
    }
  } catch {}

  const esc = (s) => String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");

  const rows = tickets.slice(0, 6).map((t) => {
    const g = esc(t.gtn);
    const u = esc(t.url);
    return `
      <div class="tkt-row">
        <div class="tkt-left"><strong>${g || "Ticket"}</strong></div>
        <div class="tkt-actions">
          ${g ? `<button class="mini copyBtn" data-copy="${g}">Copy</button>` : ""}
          ${u ? `<button class="mini openLinkBtn" data-url="${u}">Open</button>` : ""}
        </div>
      </div>
    `;
  }).join("");

  inner.innerHTML = `
    <div class="tkt-card">
      <div class="tkt-title">🎫 <strong>Ticket</strong></div>
      ${bookingId ? `<div class="tkt-meta">Booking: <strong>${esc(bookingId)}</strong></div>` : ""}
      ${tickets.length ? `<div class="tkt-list">${rows}</div>` : `<div class="tkt-empty">${ok ? "Ticket details not available yet." : "Couldn’t load ticket."}</div>`}
      ${bookingUrl ? `<div class="tkt-footer"><button class="mini openLinkBtn" data-url="${esc(bookingUrl)}">Open booking ticket</button></div>` : ""}
    </div>
  `;
  _wireCopyButtons(inner);
  inner.querySelectorAll(".openLinkBtn").forEach((b) => {
    b.addEventListener("click", () => {
      const url = b.getAttribute("data-url");
      if (!url) return;
      try { window.open(url, "_blank", "noopener"); } catch {}
    });
  });
  return bubble;
}

function addManageResultCard(kind, resp) {
  const bubble = addMessage("bot", "");
  const inner = bubble.querySelector(".bubbleInner");
  if (!inner) return bubble;
  const esc = (s) => String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");

  if (kind === "open_ended") {
    const allow = String(resp?.allow_open || "").toUpperCase() === "Y";
    inner.innerHTML = `
      <div class="mg-card">
        <div class="mg-title"><strong>Open-ended ticket</strong></div>
        <div class="mg-line">${allow ? "✅ Ticket converted to open-ended (if supported by carrier)." : "Not available for this ticket."}</div>
        <details class="mg-details"><summary>Details</summary><pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre></details>
      </div>
    `;
    return bubble;
  }
  if (kind === "set_travel_date") {
    const allow = String(resp?.allow_rebooking || "").toUpperCase() === "Y";
    inner.innerHTML = `
      <div class="mg-card">
        <div class="mg-title"><strong>Change travel date</strong></div>
        <div class="mg-line">${allow ? "✅ Rebooking request created." : "Rebooking not available for this ticket."}</div>
        <details class="mg-details"><summary>Details</summary><pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre></details>
      </div>
    `;
    return bubble;
  }
  inner.innerHTML = `<pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre>`;
  return bubble;
}

  return { html, expiresIso: expiresIso || null };
}


  function _makeAvatar(role) {
    const a = document.createElement("div");
    a.className = `avatar ${role}`;
    a.textContent = role === "user" ? "YOU" : "BX";
    a.setAttribute("aria-hidden", "true");
    return a;
  }

  function _makeContent() {
    const c = document.createElement("div");
    c.className = "content";
    return c;
  }

  function _makeBubbleInner() {
    const inner = document.createElement("div");
    inner.className = "bubbleInner";
    return inner;
  }

  // WhatsApp-like in-bubble time badge (bottom-right)
  function _applyBubbleTime(bubbleEl, text) {
    if (!bubbleEl || !text) return;
    const t = document.createElement("div");
    t.className = "btime";
    t.textContent = text;
    bubbleEl.appendChild(t);
  }

  // -------------------------------------------------------------------------
  // Busy pill (header indicator)
  // -------------------------------------------------------------------------
  function setBusy(on, text) {
    if (!busyPill) return; // avoid crashing if markup missing
    busyPill.classList.toggle("show", !!on);
    if (busyText && text) busyText.textContent = text;

    // In-chat busy indicator: a temporary bot bubble that shows ONLY dancing dots (no text).
    // Removed automatically when busy ends.
    try {
      const BUSY_STATUS_ID = "__busy_dots__";
      if (on) {
        const existing = chatEl && chatEl.querySelector ? chatEl.querySelector(`[data-msg-id="${BUSY_STATUS_ID}"]`) : null;
        if (!existing) {
          const b = addMessage("bot", "", { id: BUSY_STATUS_ID, isStatus: true });
          const inner = b && b.querySelector ? b.querySelector(".bubbleInner") : null;
          if (inner) inner.innerHTML = `<div class="dots" aria-hidden="true"><span></span><span></span><span></span></div>`;
        }
      } else {
        removeMessage(BUSY_STATUS_ID);
      }
    } catch {
      // ignore
    }


    // Global busy flag for CSS + disabling interactive controls (prevents double taps)
    try {
      document.documentElement.classList.toggle("isBusy", !!on);
      document.documentElement.setAttribute("aria-busy", on ? "true" : "false");
      // Disable interactive buttons inside chat only (keep header reset/cancel usable)
      const buttons = chatEl?.querySelectorAll?.("button") || [];
      buttons.forEach((b) => {
        if (on) {
          if (b.getAttribute("data-busy-lock") === "1") return;
          b.setAttribute("data-busy-lock", "1");
          b.setAttribute("data-was-disabled", b.disabled ? "1" : "0");
          b.disabled = true;
        } else {
          if (b.getAttribute("data-busy-lock") !== "1") return;
          const was = b.getAttribute("data-was-disabled") === "1";
          b.disabled = was;
          b.removeAttribute("data-was-disabled");
          b.removeAttribute("data-busy-lock");
        }
      });
    } catch {
      // ignore
    }
  }

  // -------------------------------------------------------------------------
  // Messages
  // -------------------------------------------------------------------------

  // Backward-compatible: returns the bubble element (like your original file)
  function addMessage(role, text, opts = {}) {
    const row = document.createElement("div");
    row.className = `msg ${role}`;
    if (opts.id) row.dataset.msgId = String(opts.id);

    const avatar = _makeAvatar(role);
    const content = _makeContent();

    const bubble = document.createElement("div");
    bubble.className = "bubble";

    const inner = _makeBubbleInner();
const _trav = _formatTravelerSummary(text);
if (_trav && _trav.html) {
  inner.innerHTML = _trav.html;
  // countdown inside the message
  const cd = inner.querySelector(".travsum-countdown");
  if (cd) _installCountdown(cd, cd.getAttribute("data-expires"));
  _wireCopyButtons(inner);
  _wireReservationButtons(inner);
} else {
  inner.textContent = String(text ?? "");
}
bubble.appendChild(inner);

_applyBubbleTime(bubble, opts.meta || _nowHM());

    if (opts.isStatus) {
      row.classList.add("status");
      bubble.classList.add("status");
      bubble.setAttribute("aria-live", "polite");
    }

    // Attach a tiny handle so we can remove/update later even if caller only kept the bubble
    bubble.__row = row;
    bubble.__msgId = opts.id || null;


    content.appendChild(bubble);
    row.appendChild(avatar);
    row.appendChild(content);
    chatEl.appendChild(row);
    scrollToBottom();
    return bubble;
  }

  function _findRowFromArg(handleOrIdOrBubble) {
    if (!handleOrIdOrBubble) return null;

    // Bubble element (from addMessage)
    if (handleOrIdOrBubble.__row) return handleOrIdOrBubble.__row;

    // Handle object { row, bubble, id }
    if (handleOrIdOrBubble.row) return handleOrIdOrBubble.row;

    // ID string
    const id = String(handleOrIdOrBubble);
    try {
      return chatEl.querySelector(`[data-msg-id="${CSS.escape(id)}"]`);
    } catch {
      // CSS.escape missing in very old browsers — fallback
      return chatEl.querySelector(`[data-msg-id="${id.replace(/"/g, '\\"')}"]`);
    }
  }

  function removeMessage(handleOrIdOrBubble) {
    const row = _findRowFromArg(handleOrIdOrBubble);
    if (row && typeof row.remove === "function") row.remove();
  }

  function updateMessage(handleOrIdOrBubble, newText) {
    if (!handleOrIdOrBubble) return;

    // Bubble element
    if (handleOrIdOrBubble.classList && handleOrIdOrBubble.textContent != null) {
      const bubbleEl = handleOrIdOrBubble;
const inner = bubbleEl.querySelector ? bubbleEl.querySelector(".bubbleInner") : null;
const _trav = _formatTravelerSummary(newText);
if (inner) {
  if (_trav && _trav.html) {
    inner.innerHTML = _trav.html;
    const cd = inner.querySelector(".travsum-countdown");
    if (cd) _installCountdown(cd, cd.getAttribute("data-expires"));
    _wireCopyButtons(inner);
    _wireReservationButtons(inner);
  } else {
    inner.textContent = String(newText ?? "");
  }
} else {
  bubbleEl.textContent = String(newText ?? "");
}
      scrollToBottom();
      return;
    }

    // Handle / ID
    const row = _findRowFromArg(handleOrIdOrBubble);
    if (!row) return;
    const bubble = row.querySelector(".bubble");
    if (!bubble) return;
    const inner = bubble.querySelector(".bubbleInner");
    if (inner) {
  const _trav = _formatTravelerSummary(newText);
  if (_trav && _trav.html) {
    inner.innerHTML = _trav.html;
    const cd = inner.querySelector(".travsum-countdown");
    if (cd) _installCountdown(cd, cd.getAttribute("data-expires"));
    _wireCopyButtons(inner);
    _wireReservationButtons(inner);
  } else {
    inner.textContent = String(newText ?? "");
  }
} else {
  bubble.textContent = String(newText ?? "");
}
    scrollToBottom();
  }

  // Convenience for an in-chat “typing/searching…” message
  function addStatus(text, opts = {}) {
    const id =
      opts.id ||
      `status_${Date.now().toString(36)}_${Math.random().toString(36).slice(2, 8)}`;
    const bubble = addMessage("bot", text, { id, isStatus: true });
  

// -------------------------------------------------------------------------
// Ticket + Manage booking cards
// -------------------------------------------------------------------------

function addTicketCard(ticketResp, { bookingId } = {}) {
  const bubble = addMessage("bot", ""); // placeholder
  const inner = bubble.querySelector(".bubbleInner");
  if (!inner) return bubble;

  const ok = ticketResp && (ticketResp.success === true || ticketResp.success === "true");
  const data = ticketResp?.data || ticketResp?.data?.data || ticketResp?.data;

  // Expected shape (spec example): data.departure[0].ticket_data.e_ticket.ticket_list[]
  let tickets = [];
  let bookingUrl = "";
  try {
    const dep0 = (data?.departure && data.departure[0]) ? data.departure[0] : null;
    const et = dep0?.ticket_data?.e_ticket || null;
    bookingUrl = et?.ticket_url || "";
    const list = et?.ticket_list || [];
    if (Array.isArray(list)) {
      tickets = list.map((t) => ({
        gtn: t?.global_ticket_number || "",
        url: t?.ticket_url || "",
      })).filter((x) => x.gtn || x.url);
    }
  } catch {}

  const esc = (s) => String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");

  const rows = tickets.slice(0, 6).map((t) => {
    const g = esc(t.gtn);
    const u = esc(t.url);
    return `
      <div class="tkt-row">
        <div class="tkt-left"><strong>${g || "Ticket"}</strong></div>
        <div class="tkt-actions">
          ${g ? `<button class="mini copyBtn" data-copy="${g}">Copy</button>` : ""}
          ${u ? `<button class="mini openLinkBtn" data-url="${u}">Open</button>` : ""}
        </div>
      </div>
    `;
  }).join("");

  inner.innerHTML = `
    <div class="tkt-card">
      <div class="tkt-title">🎫 <strong>Ticket</strong></div>
      ${bookingId ? `<div class="tkt-meta">Booking: <strong>${esc(bookingId)}</strong></div>` : ""}
      ${tickets.length ? `<div class="tkt-list">${rows}</div>` : `<div class="tkt-empty">${ok ? "Ticket details not available yet." : "Couldn’t load ticket."}</div>`}
      ${bookingUrl ? `<div class="tkt-footer"><button class="mini openLinkBtn" data-url="${esc(bookingUrl)}">Open booking ticket</button></div>` : ""}
    </div>
  `;
  _wireCopyButtons(inner);
  inner.querySelectorAll(".openLinkBtn").forEach((b) => {
    b.addEventListener("click", () => {
      const url = b.getAttribute("data-url");
      if (!url) return;
      try { window.open(url, "_blank", "noopener"); } catch {}
    });
  });
  return bubble;
}

function addManageResultCard(kind, resp) {
  const bubble = addMessage("bot", "");
  const inner = bubble.querySelector(".bubbleInner");
  if (!inner) return bubble;
  const esc = (s) => String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");

  if (kind === "open_ended") {
    const allow = String(resp?.allow_open || "").toUpperCase() === "Y";
    inner.innerHTML = `
      <div class="mg-card">
        <div class="mg-title"><strong>Open-ended ticket</strong></div>
        <div class="mg-line">${allow ? "✅ Ticket converted to open-ended (if supported by carrier)." : "Not available for this ticket."}</div>
        <details class="mg-details"><summary>Details</summary><pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre></details>
      </div>
    `;
    return bubble;
  }
  if (kind === "set_travel_date") {
    const allow = String(resp?.allow_rebooking || "").toUpperCase() === "Y";
    inner.innerHTML = `
      <div class="mg-card">
        <div class="mg-title"><strong>Change travel date</strong></div>
        <div class="mg-line">${allow ? "✅ Rebooking request created." : "Rebooking not available for this ticket."}</div>
        <details class="mg-details"><summary>Details</summary><pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre></details>
      </div>
    `;
    return bubble;
  }
  inner.innerHTML = `<pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre>`;
  return bubble;
}

  return { id, row: bubble.__row, bubble };
  }

  // -------------------------------------------------------------------------
  // Buttons bubble
  // -------------------------------------------------------------------------
  function addButtonsBubble({ title, options, onPick }) {
    const row = document.createElement("div");
    row.className = "msg bot";

    const avatar = _makeAvatar("bot");
    const content = _makeContent();
    const bubble = document.createElement("div");
    bubble.className = "bubble";

    const inner = _makeBubbleInner();

    if (title) {
      const t = document.createElement("div");
      t.textContent = title;
      t.style.marginBottom = "10px";
      t.style.fontWeight = "800";
      inner.appendChild(t);
    }

    const menu = document.createElement("div");
    menu.className = "menu";
    let used = false;

    for (const opt of options) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "choice" + (opt.primary ? " primary" : "") + (opt.danger ? " danger" : "");
      btn.textContent = opt.label;

      btn.addEventListener("click", async () => {
        if (used) return;
        used = true;
        Array.from(menu.querySelectorAll("button")).forEach((b) => (b.disabled = true));
        btn.classList.add("selected");
        await onPick(opt);
      });

      menu.appendChild(btn);
    }

    inner.appendChild(menu);
    bubble.appendChild(inner);
    _applyBubbleTime(bubble, _nowHM());
    content.appendChild(bubble);
    row.appendChild(avatar);
    row.appendChild(content);
    chatEl.appendChild(row);
    scrollToBottom();
  }

  // -------------------------------------------------------------------------
  // Passenger details bubble (form)
  // -------------------------------------------------------------------------
  function addPassengerDetailsBubble({ title, defaults = {}, onSubmit }) {
    const row = document.createElement("div");
    row.className = "msg bot";

    const avatar = _makeAvatar("bot");
    const content = _makeContent();
    const bubble = document.createElement("div");
    bubble.className = "bubble";
    const inner = _makeBubbleInner();

    if (title) {
      const t = document.createElement("div");
      t.textContent = title;
      t.style.marginBottom = "10px";
      t.style.fontWeight = "800";
      inner.appendChild(t);
    }

    const form = document.createElement("form");
    form.className = "pd-form";

    const mkInput = (label, name, type = "text", placeholder = "") => {
      const wrap = document.createElement("label");
      wrap.className = "pd-field";
      const l = document.createElement("div");
      l.className = "pd-label";
      l.textContent = label;
      const inp = document.createElement("input");
      inp.name = name;
      inp.type = type;
      inp.placeholder = placeholder;
      inp.autocomplete = name;
      inp.value = (defaults && defaults[name]) ? String(defaults[name]) : "";
      inp.required = true;
      wrap.appendChild(l);
      wrap.appendChild(inp);
      return { wrap, inp };
    };

    const mkSelect = (label, name, options) => {
      const wrap = document.createElement("label");
      wrap.className = "pd-field";
      const l = document.createElement("div");
      l.className = "pd-label";
      l.textContent = label;
      const sel = document.createElement("select");
      sel.name = name;
      sel.required = true;
      for (const o of options) {
        const opt = document.createElement("option");
        opt.value = o.value;
        opt.textContent = o.label;
        sel.appendChild(opt);
      }
      if (defaults && defaults[name]) sel.value = String(defaults[name]);
      wrap.appendChild(l);
      wrap.appendChild(sel);
      return { wrap, sel };
    };

    const first = mkInput("First name", "first", "text", "John");
    const last = mkInput("Last name", "last", "text", "Doe");
    const email = mkInput("Email", "email", "email", "you@example.com");
    const phone = mkInput("Phone", "phone", "tel", "0812345678");

    const titleId = mkSelect("Title", "title_id", [
      { value: "1", label: "Mr" },
      { value: "2", label: "Ms" },
    ]);

    const row2 = document.createElement("div");
    row2.className = "pd-row2";
    row2.appendChild(titleId.wrap);

    // Title first
    form.appendChild(row2);
    form.appendChild(first.wrap);
    form.appendChild(last.wrap);
    form.appendChild(email.wrap);
    form.appendChild(phone.wrap);

    // Autofocus first field for faster entry
    setTimeout(() => { try { first.inp.focus(); } catch {} }, 0);

    const err = document.createElement("div");
    err.className = "pd-error";
    err.style.display = "none";

    const actions = document.createElement("div");
    actions.className = "pd-actions";
    const btn = document.createElement("button");
    btn.type = "submit";
    btn.className = "choice primary";
    btn.textContent = "Continue";
    actions.appendChild(btn);

    let used = false;
    form.addEventListener("submit", async (e) => {
      e.preventDefault();
      if (used) return;
      err.style.display = "none";

      const setErr = (msg, focusEl) => {
        err.textContent = msg;
        err.style.display = "block";
        if (focusEl && typeof focusEl.focus === "function") {
          try { focusEl.focus(); } catch {}
        }
      };

      const payload = {
        first: String(first.inp.value || "").trim(),
        last: String(last.inp.value || "").trim(),
        email: String(email.inp.value || "").trim(),
        phone: String(phone.inp.value || "").trim(),
        gender: (String(titleId.sel.value || "1") === "1" ? "M" : "F"),
        title_id: String(titleId.sel.value || "1"),
        country: "TH",
      };

      // Required-field messages (specific + focused)
      if (!payload.title_id) return setErr("Title is required.", titleId.sel);
      if (!payload.first) return setErr("First name is required.", first.inp);
      if (!payload.last) return setErr("Last name is required.", last.inp);
      if (!payload.email) return setErr("Email is required.", email.inp);
      if (!payload.phone) return setErr("Phone is required.", phone.inp);

      if (!/^\S+@\S+\.\S+$/.test(payload.email)) {
        return setErr("Please enter a valid email address.", email.inp);
      }

      used = true;
      btn.disabled = true;
      btn.textContent = "Submitting…";
      try {
        await onSubmit(payload);
      } finally {
        // keep disabled; flow continues
      }
    });

    form.appendChild(err);
    form.appendChild(actions);

    inner.appendChild(form);
    bubble.appendChild(inner);
    _applyBubbleTime(bubble, _nowHM());
    content.appendChild(bubble);
    row.appendChild(avatar);
    row.appendChild(content);
    chatEl.appendChild(row);
    scrollToBottom();
  }

  // -------------------------------------------------------------------------
  // Seat map bubble (tap-to-select)
  // -------------------------------------------------------------------------
  function _seatSortKey(s) {
    const m = String(s || "").trim().match(/^([A-Z]?)(\d{1,4})([A-Z]?)$/i);
    if (!m) return { n: 999999, a: String(s || "") };
  

// -------------------------------------------------------------------------
// Ticket + Manage booking cards
// -------------------------------------------------------------------------

function addTicketCard(ticketResp, { bookingId } = {}) {
  const bubble = addMessage("bot", ""); // placeholder
  const inner = bubble.querySelector(".bubbleInner");
  if (!inner) return bubble;

  const ok = ticketResp && (ticketResp.success === true || ticketResp.success === "true");
  const data = ticketResp?.data || ticketResp?.data?.data || ticketResp?.data;

  // Expected shape (spec example): data.departure[0].ticket_data.e_ticket.ticket_list[]
  let tickets = [];
  let bookingUrl = "";
  try {
    const dep0 = (data?.departure && data.departure[0]) ? data.departure[0] : null;
    const et = dep0?.ticket_data?.e_ticket || null;
    bookingUrl = et?.ticket_url || "";
    const list = et?.ticket_list || [];
    if (Array.isArray(list)) {
      tickets = list.map((t) => ({
        gtn: t?.global_ticket_number || "",
        url: t?.ticket_url || "",
      })).filter((x) => x.gtn || x.url);
    }
  } catch {}

  const esc = (s) => String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");

  const rows = tickets.slice(0, 6).map((t) => {
    const g = esc(t.gtn);
    const u = esc(t.url);
    return `
      <div class="tkt-row">
        <div class="tkt-left"><strong>${g || "Ticket"}</strong></div>
        <div class="tkt-actions">
          ${g ? `<button class="mini copyBtn" data-copy="${g}">Copy</button>` : ""}
          ${u ? `<button class="mini openLinkBtn" data-url="${u}">Open</button>` : ""}
        </div>
      </div>
    `;
  }).join("");

  inner.innerHTML = `
    <div class="tkt-card">
      <div class="tkt-title">🎫 <strong>Ticket</strong></div>
      ${bookingId ? `<div class="tkt-meta">Booking: <strong>${esc(bookingId)}</strong></div>` : ""}
      ${tickets.length ? `<div class="tkt-list">${rows}</div>` : `<div class="tkt-empty">${ok ? "Ticket details not available yet." : "Couldn’t load ticket."}</div>`}
      ${bookingUrl ? `<div class="tkt-footer"><button class="mini openLinkBtn" data-url="${esc(bookingUrl)}">Open booking ticket</button></div>` : ""}
    </div>
  `;
  _wireCopyButtons(inner);
  inner.querySelectorAll(".openLinkBtn").forEach((b) => {
    b.addEventListener("click", () => {
      const url = b.getAttribute("data-url");
      if (!url) return;
      try { window.open(url, "_blank", "noopener"); } catch {}
    });
  });
  return bubble;
}

function addManageResultCard(kind, resp) {
  const bubble = addMessage("bot", "");
  const inner = bubble.querySelector(".bubbleInner");
  if (!inner) return bubble;
  const esc = (s) => String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");

  if (kind === "open_ended") {
    const allow = String(resp?.allow_open || "").toUpperCase() === "Y";
    inner.innerHTML = `
      <div class="mg-card">
        <div class="mg-title"><strong>Open-ended ticket</strong></div>
        <div class="mg-line">${allow ? "✅ Ticket converted to open-ended (if supported by carrier)." : "Not available for this ticket."}</div>
        <details class="mg-details"><summary>Details</summary><pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre></details>
      </div>
    `;
    return bubble;
  }
  if (kind === "set_travel_date") {
    const allow = String(resp?.allow_rebooking || "").toUpperCase() === "Y";
    inner.innerHTML = `
      <div class="mg-card">
        <div class="mg-title"><strong>Change travel date</strong></div>
        <div class="mg-line">${allow ? "✅ Rebooking request created." : "Rebooking not available for this ticket."}</div>
        <details class="mg-details"><summary>Details</summary><pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre></details>
      </div>
    `;
    return bubble;
  }
  inner.innerHTML = `<pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre>`;
  return bubble;
}

  return {
      n: parseInt(m[2], 10),
      a: ((m[1] || "") + (m[3] || "")).toUpperCase(),
    };
  }

  function addSeatMapBubble({ title, seats, pax, selected = [], onSubmit }) {
    const want = Math.max(1, parseInt(pax || 1, 10));

    // seats can be:
    //  - Array<string> of available seat numbers (legacy)
    //  - Object containing BusX get_seat_layouts data (floor_details + seat_layout_details)
    const isLayout = !!seats && typeof seats === "object" && !Array.isArray(seats) && Array.isArray(seats.seat_layout_details);

    function _layoutFloors(layout) {
      const floors = Array.isArray(layout.floor_details) && layout.floor_details.length
        ? layout.floor_details.map((f) => ({
            z: parseInt(f.floor || f.z || 1, 10) || 1,
            rows: parseInt(f.row_amount || f.rows || 0, 10) || 0,
            cols: parseInt(f.col_amount || f.cols || 0, 10) || 0,
          }))
        : [{ z: 1, rows: 0, cols: 0 }];

      // Build map: z -> (y,x) -> cell
      const byFloor = new Map();
      const details = Array.isArray(layout.seat_layout_details) ? layout.seat_layout_details : [];
      for (const it of details) {
        const z = parseInt(it.z || it.floor || 1, 10) || 1;
        const y = parseInt(it.y || it.row || 1, 10) || 1;
        const x = parseInt(it.x || it.col || 1, 10) || 1;
        if (!byFloor.has(z)) byFloor.set(z, new Map());
        byFloor.get(z).set(`${y},${x}`, it);
      }

      // If row/col not provided, infer max from details
      for (const f of floors) {
        if (f.rows && f.cols) continue;
        let maxY = 0, maxX = 0;
        const m = byFloor.get(f.z);
        if (m) {
          for (const k of m.keys()) {
            const [yy, xx] = k.split(",").map((n) => parseInt(n, 10) || 0);
            if (yy > maxY) maxY = yy;
            if (xx > maxX) maxX = xx;
          }
        }
        f.rows = f.rows || maxY || 1;
        f.cols = f.cols || maxX || 1;
      }

      // Available seats set (for selection constraints)
      const avail = new Set();
      for (const it of details) {
        if (String(it.object_code || "").toLowerCase() !== "seat") continue;
        const s = it.object_code_seat || it.seat || null;
        const num = (s && s.seat_number) ? String(s.seat_number).toUpperCase() : "";
        const status = (s && s.seat_status) ? String(s.seat_status).toLowerCase() : "";
        if (num && status === "available") avail.add(num);
      }

    

// -------------------------------------------------------------------------
// Ticket + Manage booking cards
// -------------------------------------------------------------------------

function addTicketCard(ticketResp, { bookingId } = {}) {
  const bubble = addMessage("bot", ""); // placeholder
  const inner = bubble.querySelector(".bubbleInner");
  if (!inner) return bubble;

  const ok = ticketResp && (ticketResp.success === true || ticketResp.success === "true");
  const data = ticketResp?.data || ticketResp?.data?.data || ticketResp?.data;

  // Expected shape (spec example): data.departure[0].ticket_data.e_ticket.ticket_list[]
  let tickets = [];
  let bookingUrl = "";
  try {
    const dep0 = (data?.departure && data.departure[0]) ? data.departure[0] : null;
    const et = dep0?.ticket_data?.e_ticket || null;
    bookingUrl = et?.ticket_url || "";
    const list = et?.ticket_list || [];
    if (Array.isArray(list)) {
      tickets = list.map((t) => ({
        gtn: t?.global_ticket_number || "",
        url: t?.ticket_url || "",
      })).filter((x) => x.gtn || x.url);
    }
  } catch {}

  const esc = (s) => String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");

  const rows = tickets.slice(0, 6).map((t) => {
    const g = esc(t.gtn);
    const u = esc(t.url);
    return `
      <div class="tkt-row">
        <div class="tkt-left"><strong>${g || "Ticket"}</strong></div>
        <div class="tkt-actions">
          ${g ? `<button class="mini copyBtn" data-copy="${g}">Copy</button>` : ""}
          ${u ? `<button class="mini openLinkBtn" data-url="${u}">Open</button>` : ""}
        </div>
      </div>
    `;
  }).join("");

  inner.innerHTML = `
    <div class="tkt-card">
      <div class="tkt-title">🎫 <strong>Ticket</strong></div>
      ${bookingId ? `<div class="tkt-meta">Booking: <strong>${esc(bookingId)}</strong></div>` : ""}
      ${tickets.length ? `<div class="tkt-list">${rows}</div>` : `<div class="tkt-empty">${ok ? "Ticket details not available yet." : "Couldn’t load ticket."}</div>`}
      ${bookingUrl ? `<div class="tkt-footer"><button class="mini openLinkBtn" data-url="${esc(bookingUrl)}">Open booking ticket</button></div>` : ""}
    </div>
  `;
  _wireCopyButtons(inner);
  inner.querySelectorAll(".openLinkBtn").forEach((b) => {
    b.addEventListener("click", () => {
      const url = b.getAttribute("data-url");
      if (!url) return;
      try { window.open(url, "_blank", "noopener"); } catch {}
    });
  });
  return bubble;
}

function addManageResultCard(kind, resp) {
  const bubble = addMessage("bot", "");
  const inner = bubble.querySelector(".bubbleInner");
  if (!inner) return bubble;
  const esc = (s) => String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");

  if (kind === "open_ended") {
    const allow = String(resp?.allow_open || "").toUpperCase() === "Y";
    inner.innerHTML = `
      <div class="mg-card">
        <div class="mg-title"><strong>Open-ended ticket</strong></div>
        <div class="mg-line">${allow ? "✅ Ticket converted to open-ended (if supported by carrier)." : "Not available for this ticket."}</div>
        <details class="mg-details"><summary>Details</summary><pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre></details>
      </div>
    `;
    return bubble;
  }
  if (kind === "set_travel_date") {
    const allow = String(resp?.allow_rebooking || "").toUpperCase() === "Y";
    inner.innerHTML = `
      <div class="mg-card">
        <div class="mg-title"><strong>Change travel date</strong></div>
        <div class="mg-line">${allow ? "✅ Rebooking request created." : "Rebooking not available for this ticket."}</div>
        <details class="mg-details"><summary>Details</summary><pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre></details>
      </div>
    `;
    return bubble;
  }
  inner.innerHTML = `<pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre>`;
  return bubble;
}

  return { floors, byFloor, avail };
    }

    const seatList = Array.isArray(seats) ? seats.slice() : [];
    seatList.sort((a, b) => {
      const ka = _seatSortKey(a);
      const kb = _seatSortKey(b);
      if (ka.n !== kb.n) return ka.n - kb.n;
      return ka.a.localeCompare(kb.a);
    });

    const layoutMeta = isLayout ? _layoutFloors(seats) : null;
    const upperAvail = new Set(
      isLayout ? Array.from(layoutMeta.avail) : seatList.map((x) => String(x).toUpperCase())
    );

    const picked = new Set(
      (Array.isArray(selected) ? selected : [])
        .map((x) => String(x).toUpperCase())
        .filter((x) => upperAvail.has(x))
    );

    const row = document.createElement("div");
    row.className = "msg bot";

    const avatar = _makeAvatar("bot");
    const content = _makeContent();

    const bubble = document.createElement("div");
    bubble.className = "bubble seatmap";

    const inner = _makeBubbleInner();

    const head = document.createElement("div");
    head.className = "seatmap-head";

    const h = document.createElement("div");
    h.className = "seatmap-title";
    h.textContent = title || "Choose seats";

    // Fullscreen toggle (mobile-friendly)
    const fsBtn = document.createElement("button");
    fsBtn.type = "button";
    fsBtn.className = "seatmap-fs";
    fsBtn.textContent = "Full screen";

    const _setFullscreen = (on) => {
      bubble.classList.toggle("fullscreen", !!on);
      document.documentElement.classList.toggle("seatFull", !!on);
      fsBtn.textContent = on ? "Close" : "Full screen";
      // Ensure grid is visible after transitions
      setTimeout(() => scrollToBottom(), 50);
    };

    fsBtn.addEventListener("click", () => {
      _setFullscreen(!bubble.classList.contains("fullscreen"));
    });

    const sub = document.createElement("div");
    sub.className = "seatmap-sub";

    const selectedLine = document.createElement("div");
    selectedLine.className = "seatmap-selected";

    const legend = document.createElement("div");
    legend.className = "seatmap-legend";
    legend.innerHTML = `
      <div class="seatmap-chip"><span class="seatmap-dot avail"></span>Available</div>
      <div class="seatmap-chip"><span class="seatmap-dot sel"></span>Selected</div>
      <div class="seatmap-chip"><span class="seatmap-dot unavail"></span>Unavailable</div>
      <div class="seatmap-chip"><span class="seatmap-dot fix"></span>Fixtures</div>
    `;

    const headTop = document.createElement("div");
    headTop.className = "seatmap-top";
    headTop.appendChild(h);
    headTop.appendChild(fsBtn);

    head.appendChild(headTop);
    head.appendChild(sub);
    head.appendChild(selectedLine);
    head.appendChild(legend);
    inner.appendChild(head);

    const grid = document.createElement("div");
    grid.className = "seatmap-grid";

    const seatBtns = new Map();
    const seatPos = new Map(); // seat -> {x,y,z}
    let walkwaySet = new Set(); // `${y},${x}` on current floor
    let currentFloorZ = 1;

    const foot = document.createElement("div");
    foot.className = "seatmap-foot";

    const clearBtn = document.createElement("button");
    clearBtn.type = "button";
    clearBtn.className = "seatmap-clear";
    clearBtn.textContent = "Clear";

    const confirmBtn = document.createElement("button");
    confirmBtn.type = "button";
    confirmBtn.className = "seatmap-confirm";
    confirmBtn.textContent = "Confirm seats";

    const autoBtn = document.createElement("button");
    autoBtn.type = "button";
    autoBtn.className = "seatmap-auto";
    autoBtn.textContent = "Auto-pick";

    // Auto-pick preference
    let autoMode = "together"; // together | window | aisle | front
    const modeBar = document.createElement("div");
    modeBar.className = "seatmap-modes";
    const modes = [
      { k: "together", t: "Together" },
      { k: "window", t: "Window" },
      { k: "aisle", t: "Aisle" },
      { k: "front", t: "Front" },
    ];
    const modeBtns = new Map();
    for (const m of modes) {
      const b = document.createElement("button");
      b.type = "button";
      b.className = "seatmap-mode";
      b.textContent = m.t;
      b.addEventListener("click", () => {
        autoMode = m.k;
        for (const bb of modeBtns.values()) bb.classList.remove("active");
        b.classList.add("active");
      });
      modeBtns.set(m.k, b);
      modeBar.appendChild(b);
    }
    modeBtns.get(autoMode)?.classList.add("active");

    function sync() {
      const count = picked.size;
      sub.textContent = `Select ${want} seat${want > 1 ? "s" : ""}. (${count}/${want})`;

      const pickedArr = Array.from(picked);
      pickedArr.sort((a, b) => {
        const ka = _seatSortKey(a);
        const kb = _seatSortKey(b);
        if (ka.n !== kb.n) return ka.n - kb.n;
        return ka.a.localeCompare(kb.a);
      });
      selectedLine.textContent = pickedArr.length ? `Selected: ${pickedArr.join(", ")}` : "";

      for (const [seat, btn] of seatBtns.entries()) {
        const on = picked.has(seat);
        btn.classList.toggle("selected", on);
        btn.setAttribute("aria-pressed", on ? "true" : "false");
      }
      confirmBtn.disabled = count !== want;
      clearBtn.disabled = count === 0;
      autoBtn.disabled = submitted;
    }

    let submitted = false;
    function lockUI() {
      submitted = true;
      sub.textContent = "Submitting…";
      confirmBtn.disabled = true;
      clearBtn.disabled = true;
      autoBtn.disabled = true;
      for (const btn of seatBtns.values()) btn.disabled = true;
    }

    function submitIfReady(auto = false) {
      if (submitted) return;
      if (picked.size !== want) return;
      lockUI();
      if (typeof onSubmit === "function") onSubmit(Array.from(picked), { auto });
    }


    
    function _autoSuggestAdjacent(seedSeat) {
      // Only for multi-seat selection
      if (want <= 1) return;
      const seed = String(seedSeat || "").toUpperCase();
      const p0 = seatPos.get(seed);
      if (!p0) return;

      // Candidates: available, same floor, not already picked
      const cands = [];
      for (const [seat, p] of seatPos.entries()) {
        if (!upperAvail.has(seat)) continue;
        if (picked.has(seat)) continue;
        if (p.z !== p0.z) continue;

        // Prefer same row, close columns (together feel)
        const dy = Math.abs((p.y || 0) - (p0.y || 0));
        const dx = Math.abs((p.x || 0) - (p0.x || 0));
        const score = dy * 10 + dx; // same row wins
        cands.push({ seat, score, dy, dx });
      }

      cands.sort((a, b) => a.score - b.score);

      for (const c of cands) {
        if (picked.size >= want) break;
        picked.add(c.seat);
      }
    }

function _togglePick(seat) {
      if (submitted) return;
      const S = String(seat || "").toUpperCase();
      if (!S || !upperAvail.has(S)) return;
      if (picked.has(S)) {
        picked.delete(S);
      } else {
        if (picked.size >= want) {
          const last = Array.from(picked).slice(-1)[0];
          if (last) picked.delete(last);
        }
        picked.add(S);
        if (want > 1 && picked.size === 1) _autoSuggestAdjacent(S);
      }
      sync();
      if (want === 1) submitIfReady(true);
    }

    function _makeSeatBtn(seat, status) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "seat";
      btn.textContent = seat;
      btn.setAttribute("aria-pressed", "false");

      const st = String(status || "").toLowerCase();
      if (st && st !== "available") {
        btn.classList.add("unavailable");
        btn.disabled = true;
      }

      btn.addEventListener("click", () => _togglePick(seat));
      seatBtns.set(seat, btn);
      return btn;
    }

    function _makeCell(it, x, y, z) {
      const obj = String(it?.object_code || "empty").toLowerCase();

      if (obj === "seat") {
        const s = it.object_code_seat || it.seat || {};
        const num = String(s.seat_number || "").toUpperCase();
        const status = String(s.seat_status || "").toLowerCase();
        const btn = _makeSeatBtn(num, status || "available");
        // Store position (used for auto-pick)
        if (num) seatPos.set(num, { x: parseInt(x || 0, 10) || 0, y: parseInt(y || 0, 10) || 0, z: parseInt(z || 0, 10) || 1 });
        return btn;
      }

      const d = document.createElement("div");
      d.className = "seatmap-cell";

      if (obj === "walkway" || obj === "empty") {
        d.classList.add("is-empty");
        d.setAttribute("aria-hidden", "true");
        return d;
      }

      d.classList.add("is-fixture");
      // Small, readable labels
      const label =
        obj === "driver" ? "DR" :
        obj === "stair" ? "ST" :
        obj === "toilet" ? "WC" :
        obj === "door" ? "DO" :
        obj === "engine" ? "EN" :
        obj.slice(0, 2).toUpperCase();

      d.textContent = label;
      d.title = obj;
      return d;
    }

    function _renderLayoutFloor(z) {
      // Clear existing
      grid.innerHTML = "";
      seatBtns.clear();
      seatPos.clear();
      currentFloorZ = z;

      const floor = (layoutMeta?.floors || []).find((f) => f.z === z) || (layoutMeta?.floors || [])[0] || { z: 1, rows: 1, cols: 1 };
      const rows = Math.max(1, parseInt(floor.rows || 1, 10));
      const cols = Math.max(1, parseInt(floor.cols || 1, 10));

      grid.style.setProperty("--cols", String(cols));
      grid.classList.add("seatmap-grid-real");

      const m = layoutMeta?.byFloor?.get(z) || new Map();
      walkwaySet = new Set();
      for (const [key, it] of m.entries()) {
        const obj = String(it?.object_code || "").toLowerCase();
        if (obj === "walkway") walkwaySet.add(key);
      }

      for (let y = 1; y <= rows; y++) {
        for (let x = 1; x <= cols; x++) {
          const it = m.get(`${y},${x}`) || { object_code: "empty" };
          grid.appendChild(_makeCell(it, x, y, z));
        }
      }

      // re-apply picked state to freshly built buttons
      sync();
    }

    if (isLayout) {
      // Optional floor selector (only if multiple floors)
      const floors = layoutMeta?.floors || [{ z: 1 }];
      if (floors.length > 1) {
        const tabs = document.createElement("div");
        tabs.className = "seatmap-floors";
        for (const f of floors) {
          const b = document.createElement("button");
          b.type = "button";
          b.className = "seatmap-floor";
          b.textContent = `Floor ${f.z}`;
          b.addEventListener("click", () => {
            for (const bb of tabs.querySelectorAll("button")) bb.classList.remove("active");
            b.classList.add("active");
            _renderLayoutFloor(f.z);
          });
          tabs.appendChild(b);
        }
        inner.insertBefore(tabs, grid);
        const first = tabs.querySelector("button");
        if (first) first.classList.add("active");
      }

      const z0 = (layoutMeta?.floors || [])[0]?.z || 1;
      _renderLayoutFloor(z0);
    } else {
      for (const s of seatList) {
        const seat = String(s).toUpperCase();
        const btn = _makeSeatBtn(seat, "available");
        grid.appendChild(btn);
      }
      sync();
    }

    function _comboChoose(arr, k) {
      const out = [];
      const pick = [];
      function rec(start, left) {
        if (left === 0) {
          out.push(pick.slice());
          return;
        }
        for (let i = start; i <= arr.length - left; i++) {
          pick.push(arr[i]);
          rec(i + 1, left - 1);
          pick.pop();
          if (out.length > 6000) return; // safety
        }
      }
      rec(0, k);
      return out;
    }

    function _autoPick() {
      if (submitted) return;

      // Prefer current floor seats for layout.
      const avail = [];
      for (const [seat, btn] of seatBtns.entries()) {
        if (!btn.disabled) avail.push(seat);
      }
      if (!avail.length) return;

      // Sort roughly front-to-back, left-to-right
      avail.sort((a, b) => {
        const pa = seatPos.get(a) || { y: 999, x: 999 };
        const pb = seatPos.get(b) || { y: 999, x: 999 };
        if (pa.y !== pb.y) return pa.y - pb.y;
        return pa.x - pb.x;
      });

      const k = want;
      const cap = Math.min(avail.length, 32); // cap brute force
      const candidates = avail.slice(0, cap);

      // Window/Aisle helpers (layout only)
      let minX = Infinity, maxX = -Infinity;
      for (const s of candidates) {
        const p = seatPos.get(s);
        if (!p) continue;
        minX = Math.min(minX, p.x);
        maxX = Math.max(maxX, p.x);
      }
      const isWindow = (seat) => {
        const p = seatPos.get(seat);
        if (!p) return false;
        return p.x === minX || p.x === maxX;
      };
      const isAisle = (seat) => {
        const p = seatPos.get(seat);
        if (!p) return false;
        const left = `${p.y},${p.x - 1}`;
        const right = `${p.y},${p.x + 1}`;
        return walkwaySet.has(left) || walkwaySet.has(right);
      };

      // Score a group: keep together (small max distance) + prefer front
      function score(group) {
        let maxD = 0;
        let sumY = 0;
        let sumX = 0;
        let prefPenalty = 0;
        for (let i = 0; i < group.length; i++) {
          const pi = seatPos.get(group[i]) || { x: i, y: 999 };
          sumY += pi.y;
          sumX += pi.x;

          // Preference penalties
          if (autoMode === "window" && !isWindow(group[i])) prefPenalty += 2500;
          if (autoMode === "aisle" && !isAisle(group[i])) prefPenalty += 2500;
          if (autoMode === "front") prefPenalty += pi.y * 5;

          for (let j = i + 1; j < group.length; j++) {
            const pj = seatPos.get(group[j]) || { x: j, y: 999 };
            const d = Math.abs(pi.x - pj.x) + Math.abs(pi.y - pj.y);
            if (d > maxD) maxD = d;
          }
        }
        return maxD * 10000 + prefPenalty + sumY * 100 + sumX;
      }

      let best = null;
      let bestScore = Infinity;

      if (k === 1) {
        best = [candidates[0]];
      } else {
        const combos = _comboChoose(candidates, k);
        for (const g of combos) {
          const sc = score(g);
          if (sc < bestScore) {
            bestScore = sc;
            best = g;
          }
        }
      }

      if (!best || !best.length) return;
      picked.clear();
      for (const s of best) picked.add(String(s).toUpperCase());
      sync();
    }


    clearBtn.addEventListener("click", () => {
      picked.clear();
      sync();
    });

    autoBtn.addEventListener("click", () => {
      _autoPick();
      if (want === 1) submitIfReady(true);
    });

    confirmBtn.addEventListener("click", () => submitIfReady(false));

    foot.appendChild(modeBar);
    foot.appendChild(autoBtn);
    foot.appendChild(clearBtn);
    foot.appendChild(confirmBtn);

    inner.appendChild(grid);
    inner.appendChild(foot);
    bubble.appendChild(inner);

    _applyBubbleTime(bubble, _nowHM());

    content.appendChild(bubble);
    row.appendChild(avatar);
    row.appendChild(content);
    chatEl.appendChild(row);
    scrollToBottom();
    sync();
  }

  // -------------------------------------------------------------------------
  // Summary
  // -------------------------------------------------------------------------
  function renderSummary(wizard) {
    if (sumFrom) sumFrom.textContent = wizard.from ?? "—";
    if (sumTo) sumTo.textContent = wizard.to ?? "—";
    if (sumPax) sumPax.textContent = wizard.pax ?? "—";

    // Header trip line (updates as soon as fields become available)
    if (htRoute) {
      if (wizard.from && wizard.to) htRoute.textContent = `${wizard.from} → ${wizard.to}`;
      else if (wizard.to && !wizard.from) htRoute.textContent = `To ${wizard.to}`;
      else if (wizard.from && !wizard.to) htRoute.textContent = `From ${wizard.from}`;
      else htRoute.textContent = "Choose trip";
    }

    if (htDate) {
      const d = wizard.date ? new Date(String(wizard.date)) : null;
      if (d && !isNaN(d.getTime())) {
        try {
          htDate.textContent = d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
        } catch {
          htDate.textContent = String(wizard.date);
        }
      } else {
        htDate.textContent = wizard.date ? String(wizard.date) : "—";
      }
    }

    // Sticky trip bar: show once we have FROM + TO
    const hasRoute = !!(wizard.from && wizard.to);
    if (tripbar) tripbar.classList.toggle("show", hasRoute);
    if (!hasRoute) return;

    if (tbRoute) tbRoute.textContent = `${wizard.from} → ${wizard.to}`;

    // Date (ISO -> local short)
    if (tbDate) {
      const d = wizard.date ? new Date(String(wizard.date)) : null;
      if (d && !isNaN(d.getTime())) {
        try {
          tbDate.textContent = d.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric" });
        } catch {
          tbDate.textContent = String(wizard.date);
        }
      } else {
        tbDate.textContent = wizard.date ? String(wizard.date) : "—";
      }
    }

    if (tbPax) tbPax.textContent = `${wizard.pax || "—"} pax`;
    if (tbTrip) tbTrip.textContent = wizard.trip ? String(wizard.trip) : "";
    if (tbTotal) tbTotal.textContent = wizard.total ? String(wizard.total) : "Total —";

  }

  // -------------------------------------------------------------------------

  // -------------------------------------------------------------------------
  // Progress dots
  // -------------------------------------------------------------------------
  function setProgress(state){
    if (!progressDots || !progressDotEls.length) return;
    const s = (state && typeof state === "object") ? state : {};
    const step = String(s.step || "").toUpperCase();

    const hasTrip = !!s.selected_trip || !!s.selected_trip_id || step === "PICK_TRIP" || step === "PICK_SEATS" || step === "PAYMENT_PENDING" || !!s.trip_id;
    const hasSeats = (Array.isArray(s.selected_seats) && s.selected_seats.length > 0) || !!s.seat_numbers || step === "PICK_SEATS" || step === "PAYMENT_PENDING";
    const hasBooking = !!(s.reservation_id || s.booking_id);

    const ps = String(s.payment_status || s.pay_status || s.paymentStatus || (s.order && s.order.payment && s.order.payment.payment_status) || "").toUpperCase();
    const paid = ps === "Y" || ps === "PAID" || ps === "SUCCESS" || step === "PAID" || step === "COMPLETE" || step === "DONE";

    const inPaymentStage = paid || step === "PAYMENT_PENDING" || ps === "N" || ps === "C" || !!(s.order_ref_id || (s.order && s.order.order_ref_id) || (s.order && s.order.paycode));

    const done = [
      hasTrip,
      hasSeats,
      hasBooking,
      inPaymentStage,
      paid,
    ];

    // Determine active: first incomplete dot, otherwise last.
    let activeIdx = done.findIndex((v) => !v);
    if (activeIdx < 0) activeIdx = done.length - 1;

    for (let i = 0; i < progressDotEls.length; i++) {
      const el = progressDotEls[i];
      el.classList.remove("on", "active", "done");
      if (i === 4 && paid) {
        // final dot green
        el.classList.add("done");
      } else if (done[i]) {
        el.classList.add("on");
      } else if (i === activeIdx) {
        el.classList.add("active");
      }
    }
  }

  // Skeleton helpers (premium loading feel)
  // Skeleton helpers (premium loading feel)
  // -------------------------------------------------------------------------
  function addSkeleton(kind = "lines") {
    const row = document.createElement("div");
    row.className = "msg bot";

    const avatar = _makeAvatar("bot");
    const content = _makeContent();

    const bubble = document.createElement("div");
    bubble.className = `bubble skeleton ${kind}`;

    const inner = _makeBubbleInner();
    inner.innerHTML = `
      <div class="skel-line"></div>
      <div class="skel-line"></div>
      <div class="skel-line short"></div>
    `;
    bubble.appendChild(inner);

    row.appendChild(avatar);
    content.appendChild(bubble);
    row.appendChild(content);
    chatEl.appendChild(row);
    scrollToBottom();

    bubble.__row = row;
    return bubble;
  }

  function removeSkeleton(bubble) {
    try {
      const row = bubble?.__row || bubble?.closest?.(".msg");
      row?.remove?.();
    } catch {
      // ignore
    }
  }



// -------------------------------------------------------------------------
// Ticket + Manage booking cards
// -------------------------------------------------------------------------

function addTicketCard(ticketResp, { bookingId } = {}) {
  const bubble = addMessage("bot", ""); // placeholder
  const inner = bubble.querySelector(".bubbleInner");
  if (!inner) return bubble;

  const ok = ticketResp && (ticketResp.success === true || ticketResp.success === "true");
  const data = ticketResp?.data || ticketResp?.data?.data || ticketResp?.data;

  // Expected shape (spec example): data.departure[0].ticket_data.e_ticket.ticket_list[]
  let tickets = [];
  let bookingUrl = "";
  try {
    const dep0 = (data?.departure && data.departure[0]) ? data.departure[0] : null;
    const et = dep0?.ticket_data?.e_ticket || null;
    bookingUrl = et?.ticket_url || "";
    const list = et?.ticket_list || [];
    if (Array.isArray(list)) {
      tickets = list.map((t) => ({
        gtn: t?.global_ticket_number || "",
        url: t?.ticket_url || "",
      })).filter((x) => x.gtn || x.url);
    }
  } catch {}

  const esc = (s) => String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");

  const rows = tickets.slice(0, 6).map((t) => {
    const g = esc(t.gtn);
    const u = esc(t.url);
    return `
      <div class="tkt-row">
        <div class="tkt-left"><strong>${g || "Ticket"}</strong></div>
        <div class="tkt-actions">
          ${g ? `<button class="mini copyBtn" data-copy="${g}">Copy</button>` : ""}
          ${u ? `<button class="mini openLinkBtn" data-url="${u}">Open</button>` : ""}
        </div>
      </div>
    `;
  }).join("");

  inner.innerHTML = `
    <div class="tkt-card">
      <div class="tkt-title">🎫 <strong>Ticket</strong></div>
      ${bookingId ? `<div class="tkt-meta">Booking: <strong>${esc(bookingId)}</strong></div>` : ""}
      ${tickets.length ? `<div class="tkt-list">${rows}</div>` : `<div class="tkt-empty">${ok ? "Ticket details not available yet." : "Couldn’t load ticket."}</div>`}
      ${bookingUrl ? `<div class="tkt-footer"><button class="mini openLinkBtn" data-url="${esc(bookingUrl)}">Open booking ticket</button></div>` : ""}
    </div>
  `;
  _wireCopyButtons(inner);
  inner.querySelectorAll(".openLinkBtn").forEach((b) => {
    b.addEventListener("click", () => {
      const url = b.getAttribute("data-url");
      if (!url) return;
      try { window.open(url, "_blank", "noopener"); } catch {}
    });
  });
  return bubble;
}

function addManageResultCard(kind, resp) {
  const bubble = addMessage("bot", "");
  const inner = bubble.querySelector(".bubbleInner");
  if (!inner) return bubble;
  const esc = (s) => String(s ?? "").replaceAll("&","&amp;").replaceAll("<","&lt;").replaceAll(">","&gt;").replaceAll('"',"&quot;");

  if (kind === "open_ended") {
    const allow = String(resp?.allow_open || "").toUpperCase() === "Y";
    inner.innerHTML = `
      <div class="mg-card">
        <div class="mg-title"><strong>Open-ended ticket</strong></div>
        <div class="mg-line">${allow ? "✅ Ticket converted to open-ended (if supported by carrier)." : "Not available for this ticket."}</div>
        <details class="mg-details"><summary>Details</summary><pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre></details>
      </div>
    `;
    return bubble;
  }
  if (kind === "set_travel_date") {
    const allow = String(resp?.allow_rebooking || "").toUpperCase() === "Y";
    inner.innerHTML = `
      <div class="mg-card">
        <div class="mg-title"><strong>Change travel date</strong></div>
        <div class="mg-line">${allow ? "✅ Rebooking request created." : "Rebooking not available for this ticket."}</div>
        <details class="mg-details"><summary>Details</summary><pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre></details>
      </div>
    `;
    return bubble;
  }
  inner.innerHTML = `<pre class="mg-pre">${esc(JSON.stringify(resp, null, 2))}</pre>`;
  return bubble;
}

  return {
    addMessage,
    addButtonsBubble,
    addPassengerDetailsBubble,
    addSeatMapBubble,
    renderSummary,
    setProgress,
    setBusy,

    // Skeletons
    addSkeleton,
    removeSkeleton,

    // NEW
    addStatus,
    removeMessage,
    updateMessage,

    // Ticket + manage
    addTicketCard,
    addManageResultCard,
  };
}