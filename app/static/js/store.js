export function createStore({ endpoint, userId }) {
  const storageKey = `busxBuyer:${String(userId || "default")}`;

  // Default store shape
  const store = {
    endpoint,
    userId,
    serverState: {},
    ask: null,
    lastSay: "",
    renderedAskKeys: new Set(),
    wizard: { from: null, to: null, pax: "1", date: null, trip: null, total: null },

    // Pure UI state (frontend-only). Persisted to survive refresh.
    uiState: {
      // When true, the date input expects free-typing and should show a YYYY-MM-DD hint.
      // This must ONLY flip on when the user taps "Other date…" (or manually edits date).
      dateManualEntry: false,
    },

    // Persistence helpers (refresh-safe)
    storageKey,
    load() {
      try {
        const raw = localStorage.getItem(storageKey);
        if (!raw) return;
        const j = JSON.parse(raw);
        if (j && typeof j === "object") {
          if (j.serverState && typeof j.serverState === "object") store.serverState = j.serverState;
          if (j.wizard && typeof j.wizard === "object") store.wizard = { ...store.wizard, ...j.wizard };
          if (j.ask && typeof j.ask === "object") store.ask = j.ask;
          if (typeof j.lastSay === "string") store.lastSay = j.lastSay;
          if (j.uiState && typeof j.uiState === "object") {
            store.uiState = { ...store.uiState, ...j.uiState };
          }
        }
      } catch {
        // ignore
      }
    },
    save() {
      try {
        const payload = {
          serverState: store.serverState,
          wizard: store.wizard,
          ask: store.ask,
          lastSay: store.lastSay || "",
          uiState: store.uiState,
        };
        localStorage.setItem(storageKey, JSON.stringify(payload));
      } catch {
        // ignore
      }
    },
    clear() {
      try { localStorage.removeItem(storageKey); } catch {}
      store.serverState = {};
      store.ask = null;
      store.lastSay = "";
      store.renderedAskKeys = new Set();
      store.wizard = { from: null, to: null, pax: "1", date: null, trip: null, total: null };
      store.uiState = { dateManualEntry: false };
    },
  };

  // Load persisted data immediately
  store.load();
  return store;
}

export function computeAskKey(env) {
  const ask = env?.ask || null;
  const step = String(env?.state?.step || "");
  if (!ask) return `noask|${step}`;
  const opts = Array.isArray(ask.options) ? ask.options.map((o) => o.value).join(",") : "";
  return `${ask.type}|${ask.field || ""}|${opts}|${step}`;
}
