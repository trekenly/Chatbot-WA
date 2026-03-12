import { useState, useRef } from "react";
import { DateQuickChips } from "./DateQuickChips";
import { SEAMap } from "./SEAMap";

interface Props {
  disabled?: boolean;
  onDate: (date: string) => void;
  onOtherDate: () => void;
  onDestination: (dest: string) => void;
}

const POPULAR = ["Phuket", "Chiang Mai", "Krabi", "Pattaya", "Hua Hin", "Koh Samui"];

export function WelcomeHero({ disabled, onDate, onOtherDate, onDestination }: Props) {
  const [destText, setDestText] = useState("");
  const [showSuggestions, setShowSuggestions] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const filtered = destText.trim().length > 0
    ? POPULAR.filter(p => p.toLowerCase().startsWith(destText.toLowerCase()))
    : POPULAR;

  function handleDestSubmit() {
    const val = destText.trim();
    if (val) { onDestination(val); setDestText(""); }
  }

  return (
    <div className="welcomeHero">

      {/* ── SEA Map — full-width banner ── */}
      <div className="heroMapWrap" aria-hidden="true">
        <SEAMap className="heroSeaMap" />
        {/* Fade edges so map bleeds into background */}
        <div className="heroMapFadeBottom" />
        <div className="heroMapFadeSides" />
      </div>

      {/* ── Content layer on top of map ── */}
      <div className="heroContent">

        <div className="heroHead">
          <h1 className="heroTitle">
            When would you<br />
            <span className="heroAccent">like to travel?</span>
          </h1>
          <p className="heroSub">
            Pick a date and we'll find the best buses for you.
          </p>
        </div>

        {/* ── Date chips ── */}
        <div className="heroSection">
          <DateQuickChips
            disabled={disabled}
            onPick={onDate}
            onOther={onOtherDate}
          />
        </div>

        {/* ── Destination shortcut ── */}
        <div className="heroSection">
          <div className="heroSectionLabel">Or type your destination</div>
          <div className="destInputWrap">
            <input
              ref={inputRef}
              className="destInput"
              type="text"
              placeholder="e.g. Phuket, Chiang Mai…"
              value={destText}
              disabled={disabled}
              onChange={e => { setDestText(e.target.value); setShowSuggestions(true); }}
              onFocus={() => setShowSuggestions(true)}
              onBlur={() => setTimeout(() => setShowSuggestions(false), 150)}
              onKeyDown={e => { if (e.key === "Enter") handleDestSubmit(); }}
            />
            {destText.trim() && (
              <button className="destGo btn btnPrimary" type="button" disabled={disabled} onClick={handleDestSubmit}>
                Go →
              </button>
            )}
            {showSuggestions && filtered.length > 0 && (
              <div className="destSuggestions">
                {filtered.map(p => (
                  <button
                    key={p}
                    className="destSuggItem"
                    type="button"
                    onMouseDown={() => { onDestination(p); setDestText(""); setShowSuggestions(false); }}
                  >
                    {p}
                  </button>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* ── Trust strip ── */}
        <div className="trustStrip">
          <span className="trustItem">✓ 1,500+ routes</span>
          <span className="trustDot" />
          <span className="trustItem">✓ Real-time seats</span>
          <span className="trustDot" />
          <span className="trustItem">✓ Instant confirmation</span>
        </div>

      </div>
    </div>
  );
}
