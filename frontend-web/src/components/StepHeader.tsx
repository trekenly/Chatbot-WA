import React from "react";
import type { Ask } from "../chat/types";

export type StepInfo = {
  index: number; // 1-based
  total: number;
  label: string;
};

function askKey(ask: Ask | null): string {
  const f = String(ask?.field || "").trim();
  const t = String(ask?.type || "").trim();
  return `${t}:${f}`;
}

export function deriveStepInfo(args: {
  ask: Ask | null;
  hasReservation: boolean;
}): StepInfo {
  const { ask, hasReservation } = args;

  // UX grouping (premium “guided checkout”):
  // 1) Date 2) Route 3) Passengers 4) Trip 5) Seats 6) Details 7) Pay
  const total = 7;
  if (hasReservation) return { index: 7, total, label: "Payment" };

  const key = askKey(ask);
  const field = String(ask?.field || "");
  const type = String(ask?.type || "");
  const prompt = String(ask?.prompt || "").toLowerCase();

  if (field === "departure_date" || field === "date" || key.includes(":departure_date")) {
    return { index: 1, total, label: "Travel date" };
  }

  if (field === "to" || field === "from") {
    return { index: 2, total, label: "Route" };
  }

  if (field === "pax") {
    return { index: 3, total, label: "Passengers" };
  }

  // Trip selection usually arrives as a choice menu (type=choice) with a prompt mentioning trip.
  if (type === "choice" && (prompt.includes("trip") || prompt.includes("departure") || prompt.includes("select"))) {
    return { index: 4, total, label: "Choose trip" };
  }

  if (type === "seatmap") {
    return { index: 5, total, label: "Seats" };
  }

  if (field === "passenger_details") {
    return { index: 6, total, label: "Passenger details" };
  }

  // Fallbacks:
  if (type === "choice") return { index: 4, total, label: "Choose" };
  return { index: 1, total, label: "Travel date" };
}

export function StepHeader(props: { step: StepInfo }) {
  const { step } = props;
  const dots = Array.from({ length: step.total }, (_, i) => i + 1);
  return (
    <div className="stepBar" aria-label={`Step ${step.index} of ${step.total}`}>
      <div className="stepLeft">
        <div className="stepKicker">Step {step.index} of {step.total}</div>
        <div className="stepLabel">{step.label}</div>
      </div>
      <div className="stepDots" aria-hidden="true">
        {dots.map((n) => (
          <span
            key={n}
            className={
              n === step.index
                ? "stepDot stepDotActive"
                : n < step.index
                  ? "stepDot stepDotDone"
                  : "stepDot"
            }
          />
        ))}
      </div>
    </div>
  );
}
