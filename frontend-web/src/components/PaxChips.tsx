import React from "react";

const PAX = [1,2,3,4,5,6,7,8,9,10];

export function PaxChips({ disabled, title, onPick }:{
  disabled?: boolean;
  title?: string;
  onPick:(v:string)=>void;
}) {
  return (
    <div>
      {title ? <div style={{ fontWeight: 700, marginBottom: 8 }}>{title}</div> : null}
      <div className="chips">
        {PAX.map((n) => (
          <button key={n} className="chip" disabled={disabled} onClick={() => onPick(String(n))} type="button">
            {n}
          </button>
        ))}
      </div>
    </div>
  );
}
