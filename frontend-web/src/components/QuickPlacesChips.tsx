import React from "react";
import { safeGetStorage, safeSetStorage } from "../lib/storage";

const LS_LAST_FROM = "busx_last_from";
const LS_LAST_TO   = "busx_last_to";

const QUICK_TO = [
  "Phuket",
  "Chiang Mai",
  "Krabi",
  "Pattaya",
  "Hua Hin",
  "Koh Samui",
  "Surat Thani",
  "Ayutthaya",
  "__OTHER__",
];

const QUICK_FROM = [
  "Bangkok",
  "Chiang Mai",
  "Phuket",
  "Pattaya",
  "Krabi",
  "Hua Hin",
  "Surat Thani",
  "Koh Samui",
];

export function QuickFromChips({ disabled, title, onPick }: {
  disabled?: boolean;
  title?: string;
  onPick: (v: string) => void;
}) {
  const last = safeGetStorage(LS_LAST_FROM).trim();
  const list = last && !QUICK_FROM.includes(last) ? [last, ...QUICK_FROM] : QUICK_FROM;
  return (
    <div>
      {title ? <div style={{ fontWeight: 700, marginBottom: 8 }}>{title}</div> : null}
      <div className="chips">
        {list.map((x) => {
          const isLast = !!last && x === last;
          return (
            <button
              key={isLast ? `__LAST__${x}` : x}
              className="chip"
              disabled={disabled}
              onClick={() => {
                safeSetStorage(LS_LAST_FROM, x);
                onPick(x);
              }}
              type="button"
              title={isLast ? "Use your most recent departure" : undefined}
            >
              {x}
            </button>
          );
        })}
      </div>
    </div>
  );
}

export function QuickToChips({ disabled, title, onPick }: {
  disabled?: boolean;
  title?: string;
  onPick: (v: string) => void;
}) {
  const last = safeGetStorage(LS_LAST_TO).trim();
  const list = last && !QUICK_TO.includes(last) ? [last, ...QUICK_TO] : QUICK_TO;
  return (
    <div>
      {title ? <div style={{ fontWeight: 700, marginBottom: 8 }}>{title}</div> : null}
      <div className="chips">
        {list.map((x) => {
          const isLast = !!last && x === last;
          const label  = x === "__OTHER__" ? "Other…" : x;
          return (
            <button
              key={isLast ? `__LAST__${x}` : x}
              className="chip"
              disabled={disabled}
              onClick={() => {
                if (x !== "__OTHER__") safeSetStorage(LS_LAST_TO, x);
                onPick(x);
              }}
              type="button"
              title={isLast ? "Use your most recent destination" : undefined}
            >
              {label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
