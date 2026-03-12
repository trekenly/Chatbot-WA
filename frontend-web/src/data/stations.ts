export type BangkokTerminal = {
  id: string;
  displayName: string; // English-friendly
  thaiName: string; // Thai name for taxi driver
  hint: string; // short location hint with BTS/MRT references
  directions: string[]; // bullet list
  backendValue: string; // what we send to backend (terminal-specific)
};

// 4 major Bangkok terminals (editable)
export const BANGKOK_TERMINALS: BangkokTerminal[] = [
  {
    id: "mochit",
    displayName: "Mo Chit (Northern Bus Terminal)",
    thaiName: "สถานีขนส่งผู้โดยสารกรุงเทพ (หมอชิต 2)",
    hint: "Near BTS Mo Chit / MRT Chatuchak Park",
    directions: [
      "BTS to Mo Chit, then taxi or short ride",
      "MRT to Chatuchak Park, then taxi",
      "Taxi: say 'Mo Chit 2'",
    ],
    backendValue: "Bangkok Mo Chit",
  },
  {
    id: "ekkamai",
    displayName: "Ekkamai (Eastern Bus Terminal)",
    thaiName: "สถานีขนส่งผู้โดยสารกรุงเทพ (เอกมัย)",
    hint: "Directly at BTS Ekkamai",
    directions: [
      "BTS to Ekkamai (Exit 2), terminal is right there",
      "Taxi: say 'Bus terminal Ekkamai'",
    ],
    backendValue: "Bangkok Ekkamai",
  },
  {
    id: "saitai",
    displayName: "Sai Tai Mai (Southern Bus Terminal)",
    thaiName: "สถานีขนส่งผู้โดยสารกรุงเทพ (สายใต้ใหม่)",
    hint: "Taling Chan area (typically taxi/Grab)",
    directions: [
      "Taxi/Grab recommended (far from BTS/MRT)",
      "If using transit: go toward Taling Chan then taxi",
      "Taxi: say 'Sai Tai Mai'",
    ],
    backendValue: "Bangkok Sai Tai Mai",
  },
  {
    id: "rangsit",
    displayName: "Rangsit (for some routes)",
    thaiName: "สถานีขนส่งผู้โดยสารรังสิต",
    hint: "North Bangkok / Future Park Rangsit area",
    directions: [
      "Taxi/Grab usually easiest",
      "Some vans/minibuses depart from here",
    ],
    backendValue: "Bangkok Rangsit",
  },
];

// Destination → recommended Bangkok DEPARTURE terminal.
// Keep expanding this as you learn your actual sellable routes.
export const DESTINATION_TO_BKK_TERMINAL: Record<string, string> = {
  // South / Andaman
  "Phuket": "saitai",
  "Krabi": "saitai",
  "Trang": "saitai",
  "Satun": "saitai",
  "Chumphon": "saitai",
  "Surat Thani": "saitai",
  "Nakhon Si Thammarat": "saitai",
  "Hat Yai": "saitai",
  "Songkhla": "saitai",
  "Pattani": "saitai",
  "Yala": "saitai",
  "Narathiwat": "saitai",

  // East
  "Pattaya": "ekkamai",
  "Rayong": "ekkamai",
  "Chanthaburi": "ekkamai",
  "Trat": "ekkamai",
  "Koh Chang": "ekkamai",

  // North / Northeast
  "Chiang Mai": "mochit",
  "Chiang Rai": "mochit",
  "Phitsanulok": "mochit",
  "Sukhothai": "mochit",
  "Lampang": "mochit",
  "Lamphun": "mochit",
  "Nan": "mochit",
  "Phrae": "mochit",
  "Mae Sot": "mochit",
  "Udon Thani": "mochit",
  "Khon Kaen": "mochit",
  "Nakhon Ratchasima": "mochit",
  "Ubon Ratchathani": "mochit",
  "Buriram": "mochit",
  "Surin": "mochit",
};

function normPlace(s: string): string {
  return String(s || "")
    .trim()
    .toLowerCase()
    .replace(/\s+/g, " ");
}

export function terminalForDestination(destinationName: string | undefined | null): string | null {
  const dest = String(destinationName || "").trim();
  if (!dest) return null;
  // case-insensitive match
  const want = normPlace(dest);
  for (const [k, v] of Object.entries(DESTINATION_TO_BKK_TERMINAL)) {
    if (normPlace(k) === want) return v;
  }
  return null;
}

export function getSellableBangkokTerminals(destinationName?: string | null): BangkokTerminal[] {
  const recommendedId = terminalForDestination(destinationName);
  // Avoid Object.fromEntries for maximum browser compatibility.
  // Some older/mobile WebViews can crash on Object.fromEntries, which would blank the UI
  // exactly when this picker renders.
  const byId: Record<string, BangkokTerminal> = {};
  for (const t of BANGKOK_TERMINALS) {
    byId[t.id] = t;
  }

  // If destination is known and mapped, only show the mapped terminal.
  if (recommendedId && byId[recommendedId]) {
    return [byId[recommendedId]];
  }

  // Otherwise show only terminals that appear in the mapping values (sellable).
  const sellableIds = new Set(Object.values(DESTINATION_TO_BKK_TERMINAL));
  return BANGKOK_TERMINALS.filter((t) => sellableIds.has(t.id));
}


export function filterBangkokTerminalsByIds(ids: string[] | undefined | null): BangkokTerminal[] | null {
  if (!ids || !Array.isArray(ids) || ids.length === 0) return null;
  const want = new Set(ids.map((x) => String(x || "").trim().toLowerCase()).filter(Boolean));
  return BANGKOK_TERMINALS.filter((t) => want.has(String(t.id).toLowerCase()));
}
