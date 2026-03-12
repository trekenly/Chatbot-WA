/**
 * SEAMap — Thailand only, with city markers.
 * ViewBox tuned to fit Thailand snugly.
 * x = (lon - 97) * 14,  y = (21 - lat) * 14
 * Covers roughly 97°E–106°E, 5°N–21°N
 */

interface Props { className?: string; }

export function SEAMap({ className }: Props) {
  return (
    <svg viewBox="0 0 130 230" fill="none" xmlns="http://www.w3.org/2000/svg"
      className={className} aria-hidden="true">
      <defs>
        <radialGradient id="thGlow" cx="45%" cy="35%" r="55%">
          <stop offset="0%" stopColor="var(--accent)" stopOpacity="0.15"/>
          <stop offset="100%" stopColor="var(--accent)" stopOpacity="0"/>
        </radialGradient>
        <filter id="cityGlow" x="-100%" y="-100%" width="300%" height="300%">
          <feGaussianBlur stdDeviation="2.5" result="b"/>
          <feMerge><feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>

      <rect width="130" height="230" fill="url(#thGlow)"/>

      {/* ── MAIN BODY: North → Isan (east bulge) → Bangkok → Gulf coast ──
          lon/lat → x=(lon-97)*14, y=(21-lat)*14
          Chiang Rai  99.8°E 20.0°N → x=39.2  y=14
          Mae Sai     99.9°E 20.4°N → x=40.5  y=7
          Chiang Mai  98.9°E 18.8°N → x=26.5  y=31
          Mae Hong Son 97.9°E 19.3°N → x=12.6 y=23
          Three Pagodas 98.4°E 15.2°N → x=19.6 y=81
          Kanchanaburi 99.5°E 14.0°N → x=35   y=98
          Bangkok     100.5°E 13.7°N → x=49   y=102
          Pattaya     100.9°E 12.9°N → x=54.6 y=113
          Hua Hin     99.95°E 12.6°N → x=41.3 y=117
          Ranong      98.6°E 9.96°N  → x=22.4 y=155
          Phuket      98.4°E 7.9°N   → x=19.6 y=184
          Hat Yai     100.5°E 7.0°N  → x=49   y=196
          Sadao       100.4°E 6.6°N  → x=47.6 y=202
      */}

      {/* North + West + Isan body */}
      <path className="thBody" d="
        M 40,5
        L 46,4   L 52,5   L 58,8   L 63,12  L 66,17
        L 68,22  L 72,26  L 76,28  L 80,30  L 84,32
        L 88,34  L 90,40  L 90,46  L 88,52  L 86,58
        L 84,63  L 82,68  L 80,72  L 76,74  L 72,74
        L 68,72  L 64,70  L 60,68  L 56,66  L 52,67
        L 50,70  L 50,76  L 52,80  L 54,84  L 56,88
        L 58,92  L 58,98  L 56,103 L 53,107 L 50,110
        L 48,115 L 46,119 L 44,123 L 42,127 L 40,131
        L 38,135 L 36,139 L 34,143 L 33,147 L 34,151
        L 34,155 L 32,158 L 30,156 L 28,152 L 26,148
        L 24,144 L 22,140 L 22,135 L 24,130 L 26,125
        L 27,120 L 26,115 L 24,111 L 22,107 L 20,103
        L 18,98  L 18,93  L 20,88  L 22,83  L 23,78
        L 22,73  L 20,69  L 18,65  L 17,60  L 17,55
        L 18,50  L 20,45  L 22,40  L 24,35  L 25,30
        L 24,25  L 22,20  L 21,15  L 22,10  L 26,6
        L 32,4   L 40,5 Z
      "/>

      {/* Gulf of Thailand eastern coast bulge (Chonburi, Rayong) */}
      <path className="thBody" d="
        M 58,98  L 62,96  L 66,95  L 70,96  L 73,99
        L 74,103 L 72,107 L 68,110 L 63,111 L 59,109
        L 56,105 L 56,101 L 58,98 Z
      "/>

      {/* Southern peninsula — narrows toward Malaysia */}
      <path className="thBody" d="
        M 40,131 L 42,133 L 44,137 L 45,141 L 44,145
        L 42,149 L 40,153 L 38,157 L 36,161 L 34,165
        L 32,169 L 30,173 L 28,177 L 26,181 L 25,185
        L 24,189 L 24,193 L 25,197 L 26,201 L 27,205
        L 28,209 L 28,213 L 27,217 L 25,220 L 23,222
        L 21,220 L 20,216 L 20,212 L 21,208 L 22,204
        L 23,200 L 24,196 L 23,192 L 22,188 L 21,184
        L 20,180 L 20,176 L 21,172 L 22,168 L 23,164
        L 24,160 L 25,156 L 26,152 L 27,148 L 28,144
        L 29,140 L 30,136 L 32,133 L 34,131 L 38,131
        L 40,131 Z
      "/>

      {/* ── CITY MARKERS ── */}

      {/* Bangkok — primary */}
      <circle cx="55" cy="103" r="13" className="mapCityPulse"/>
      <circle cx="55" cy="103" r="5" className="mapCityDot mapCityPrimary" filter="url(#cityGlow)"/>

      {/* Chiang Mai */}
      <circle cx="25" cy="38" r="3.5" className="mapCityDot"/>
      {/* Phuket */}
      <circle cx="21" cy="186" r="3" className="mapCityDot"/>
      {/* Krabi */}
      <circle cx="24" cy="176" r="2.5" className="mapCityDot mapCitySmall"/>
      {/* Koh Samui */}
      <circle cx="60" cy="146" r="2.5" className="mapCityDot mapCitySmall"/>
      {/* Hua Hin */}
      <circle cx="42" cy="120" r="2.5" className="mapCityDot mapCitySmall"/>
      {/* Pattaya */}
      <circle cx="58" cy="113" r="2.5" className="mapCityDot mapCitySmall"/>
      {/* Chiang Rai */}
      <circle cx="38" cy="18" r="2" className="mapCityDot mapCitySmall"/>
      {/* Hat Yai */}
      <circle cx="26" cy="203" r="2" className="mapCityDot mapCitySmall"/>

      {/* ── LABELS ── */}
      <text x="62"  y="101" className="mapCityLabel mapCityLabelPrimary">Bangkok</text>
      <text x="30"  y="36"  className="mapCityLabel">Chiang Mai</text>
      <text x="6"   y="188" className="mapCityLabel">Phuket</text>
      <text x="64"  y="145" className="mapCityLabel">Koh Samui</text>
      <text x="46"  y="118" className="mapCityLabel">Hua Hin</text>
    </svg>
  );
}
