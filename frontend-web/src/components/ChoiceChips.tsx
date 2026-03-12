import React from "react";
import type { AskOption } from "../chat/types";

function isLikelyTripOption(s: string) {
  const t = String(s || "");
  return t.includes("→") || t.includes("->") || t.includes("|") || t.length > 40;
}

function parseTripLabel(raw: string) {
  const label = String(raw || "").trim();
  const parts = label.split("|").map((p) => p.trim()).filter(Boolean);
  const head = parts[0] || label;

  const time = head;
  const service = parts[1] || "";
  const pricePart = parts.find((p) => /THB/i.test(p)) || "";
  const seatsPart = parts.find((p) => /seats?/i.test(p)) || "";

  let price = "";
  const m = pricePart.match(/([0-9]+(?:\.[0-9]{1,2})?)\s*THB/i);
  if (m) price = `${m[1]} THB`;

  const seats = seatsPart.replace(/^seats?\s*/i, "").trim();
  const subtitle = service;

  return { time, subtitle, price, seats, raw: label };
}

type AnyOpt = AskOption | string | Record<string, any>;

function normalizeOption(o: AnyOpt): { label: string; value: string } {
  if (typeof o === "string") {
    const s = o.trim();
    return { label: s, value: s };
  }
  const any = o as any;
  const label = (any.label ?? any.value ?? any.name ?? any.text ?? any.id ?? any.keyword_id ?? any.fare_ref_id ?? "").toString();
  const value = (any.value ?? any.id ?? any.keyword_id ?? any.place_id ?? any.stop_id ?? any.fare_ref_id ?? any.label ?? any.name ?? any.text ?? "").toString();
  return { label, value };
}

export function ChoiceChips({
  disabled,
  title,
  options,
  onPick,
}: {
  disabled?: boolean;
  title?: string;
  options: AnyOpt[];
  onPick: (v: string) => void;
}) {
  const norm = (options || []).map(normalizeOption).filter((x) => x.label || x.value);

  const renderAsList = norm.some((o) => isLikelyTripOption(o.label));

  return (
    <div>
      {title ? <div style={{ fontWeight: 700, marginBottom: 8 }}>{title}</div> : null}

      {renderAsList ? (
        <div className="choiceList">
          {norm.map((o) => {
            const label = o.label;
            const value = o.value || o.label;
            const t = parseTripLabel(label);
            return (
              <button
                key={value || label}
                className="choiceRow"
                disabled={disabled}
                onClick={() => onPick(value)}
                type="button"
              >
                <div className="choiceRowMain">
                  <div className="choiceTime">{t.time}</div>
                  {t.subtitle ? <div className="choiceSub">{t.subtitle}</div> : null}
                  {t.seats ? <div className="choiceMeta">Seats {t.seats}</div> : null}
                </div>
                {t.price ? <div className="choicePrice">{t.price}</div> : null}
              </button>
            );
          })}
        </div>
      ) : (
        <div className="chips">
          {norm.map((o) => {
            const label = o.label || o.value;
            const value = o.value || o.label;
            return (
              <button
                key={value || label}
                className="chip"
                disabled={disabled}
                onClick={() => onPick(value)}
                type="button"
              >
                {label}
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
