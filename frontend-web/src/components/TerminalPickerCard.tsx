import React from "react";

// Generic "terminal/stop picker" card used for FROM disambiguation across Thailand.
// This is used when the backend returns ask.type === "choice" with ask.field === "from".

type AskOption = {
  label?: string;
  value?: string;
  description?: string;
};

type Props = {
  title: string;
  subtitle?: string;
  options: AskOption[];
  disabled?: boolean;
  onPick: (value: string, label?: string) => void;
};

export function TerminalPickerCard({ title, subtitle, options, disabled, onPick }: Props) {
  return (
    <div>
      <div style={{ fontWeight: 700, marginBottom: 2 }}>{title}</div>
      {subtitle ? (
        <div className="muted" style={{ fontSize: 12 }}>
          {subtitle}
        </div>
      ) : null}

      <div className="terminalGrid" style={{ marginTop: 10 }}>
        {options.map((o, idx) => {
          const label = String(o.label || o.value || "").trim();
          const value = String(o.value || "").trim();
          const description = String(o.description || "").trim();
          return (
            <button
              key={idx}
              type="button"
              className="terminalCard"
              disabled={disabled}
              onClick={() => onPick(value, label)}
            >
              <div style={{ fontWeight: 700 }}>{label}</div>
              {description ? (
                <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                  {description}
                </div>
              ) : value && value !== label ? (
                <div className="muted" style={{ fontSize: 12, marginTop: 4 }}>
                  {value}
                </div>
              ) : null}
            </button>
          );
        })}
      </div>
    </div>
  );
}
