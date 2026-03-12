import React, { useMemo } from "react";
import {
  BANGKOK_TERMINALS,
  filterBangkokTerminalsByIds,
  getSellableBangkokTerminals,
  terminalForDestination,
  type BangkokTerminal,
} from "../data/stations";

export function BangkokTerminalPicker(props: {
  disabled?: boolean;
  destinationName?: string;
  allowedTerminalIds?: string[];
  loading?: boolean;
  onPick: (backendValue: string) => void;
  onCancel?: () => void;
}) {
  const { disabled, destinationName, allowedTerminalIds, loading, onPick, onCancel } = props;

  const terminals: BangkokTerminal[] = useMemo(() => {
    // Base = terminals allowed by our known sellable mapping (e.g. Phuket => Sai Tai Mai only).
    // If the backend also returns an API-filtered set, INTERSECT it with the base.
    // This prevents false-positives where the probe accidentally marks a terminal sellable.
    const base = getSellableBangkokTerminals(destinationName);

    const apiFiltered = filterBangkokTerminalsByIds(allowedTerminalIds);
    const filtered = apiFiltered
      ? apiFiltered.filter((t) => base.some((b) => b.id === t.id))
      : base;
    const rec = terminalForDestination(destinationName);
    if (rec) {
      return [...filtered].sort((a, b) => (a.id === rec ? -1 : b.id === rec ? 1 : 0));
    }
    return filtered;
  }, [allowedTerminalIds, destinationName]);

  const recommendedId = useMemo(() => terminalForDestination(destinationName), [destinationName]);

  return (
    <div className="terminalPicker">
      <div className="terminalPickerHeader">
        <div>
          <div className="terminalPickerTitle">Choose your Bangkok departure terminal</div>
          {destinationName ? (
            <div className="terminalPickerSub">
              Destination: <span className="mono">{destinationName}</span>
            </div>
          ) : (
            <div className="terminalPickerSub">{loading ? "Checking sellable terminals..." : "Only showing terminals with sellable routes."}</div>
          )}
        </div>
        {onCancel && (
          <button
            type="button"
            className="btn btnGhost"
            onClick={() => onCancel()}
            disabled={disabled}
            title="Back"
          >
            Back
          </button>
        )}
      </div>

      {terminals.length === 0 ? (
        <div className="terminalEmpty">
          No sellable Bangkok terminals found for this destination.
        </div>
      ) : (
        <div className="terminalGrid">
          {terminals.map((t) => {
            const recommended = Boolean(recommendedId && t.id === recommendedId);
            return (
              <button
                key={t.id}
                type="button"
                className={`terminalCard ${recommended ? "recommended" : ""}`}
                onClick={() => onPick(t.backendValue)}
                disabled={disabled}
              >
                <div className="terminalTop">
                  <div className="terminalName">{t.displayName}</div>
                  {recommended && <div className="terminalBadge">Recommended for your route</div>}
                </div>
                <div className="terminalThai">{t.thaiName}</div>
                <div className="terminalHint">{t.hint}</div>
                <ul className="terminalDirections">
                  {t.directions.map((d, idx) => (
                    <li key={idx}>{d}</li>
                  ))}
                </ul>
              </button>
            );
          })}
        </div>
      )}
    </div>
  );
}
