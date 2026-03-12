function isoToday(daysAhead = 0): string {
  const d = new Date();
  d.setDate(d.getDate() + daysAhead);
  const yyyy = d.getFullYear();
  const mm = String(d.getMonth() + 1).padStart(2, "0");
  const dd = String(d.getDate()).padStart(2, "0");
  return `${yyyy}-${mm}-${dd}`;
}

const LS_LAST_DATE = "busx_last_date";

function safeSet(key: string, value: string) {
  try {
    localStorage.setItem(key, String(value || ""));
  } catch {
    // ignore (SSR/private mode)
  }
}

export function DateQuickChips(props: {
  disabled?: boolean;
  onPick: (value: string) => void;
  onOther?: () => void;
}) {
  const { disabled, onPick, onOther } = props;

  const pick = (v: string) => {
    // Keep behavior consistent with the rest of the app: store last picked date.
    safeSet(LS_LAST_DATE, v);
    onPick(v);
  };

  return (
    <div className="chips">
      <button
        className="chip"
        type="button"
        disabled={disabled}
        onClick={() => pick(isoToday(0))}
      >
        Today
      </button>

      <button
        className="chip"
        type="button"
        disabled={disabled}
        onClick={() => pick(isoToday(1))}
      >
        Tomorrow
      </button>

      <button
        className="chip"
        type="button"
        disabled={disabled}
        onClick={() => {
          onOther?.();
          // Best-effort: focus the composer so the user can type a date.
          const el = document.querySelector<HTMLInputElement>('input[type="text"]');
          el?.focus();
        }}
      >
        Other date…
      </button>
    </div>
  );
}
