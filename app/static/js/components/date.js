function isoToday() {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function isoTomorrow() {
  const d = new Date();
  d.setDate(d.getDate() + 1);
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, "0");
  const day = String(d.getDate()).padStart(2, "0");
  return `${y}-${m}-${day}`;
}

function isValidISODate(iso) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return false;
  const [y, m, d] = iso.split("-").map(Number);
  const dt = new Date(Date.UTC(y, m - 1, d));
  return dt.getUTCFullYear() === y && (dt.getUTCMonth() + 1) === m && dt.getUTCDate() === d;
}

export function renderDateAsk({ ui, datePickerEl, onPick, title, onOther }) {
  ui.addButtonsBubble({
    title: title || "Pick a travel date",
    options: [
      { value: "today", label: "Today" },
      { value: "tomorrow", label: "Tomorrow" },
      { value: "other", label: "Other date…" },
    ],
    onPick: async (opt) => {
      if (opt.value === "today") return onPick("today", isoToday());
      if (opt.value === "tomorrow") return onPick("tomorrow", isoTomorrow());

      if (typeof onOther === "function") { try { onOther(); } catch {} }

      // Native date picker
      datePickerEl.value = "";
      datePickerEl.onchange = async () => {
        const iso = String(datePickerEl.value || "").trim();
        if (!isValidISODate(iso)) {
          ui.addMessage("bot", "Please choose a valid date (YYYY-MM-DD)." );
          return;
        }
        await onPick(iso, iso);
      };
      datePickerEl.showPicker?.();
      datePickerEl.click();
    },
  });
}
