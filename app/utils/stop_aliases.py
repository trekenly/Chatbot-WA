"""Stop/terminal alias helpers.

These aliases help non-Thai speakers match informal station names to BusX
keyword_name values.

Example:
  - "Mo Chit" -> "Bangkok Bus Terminal Chatuchak (Mo Chit 2)"
  - "airport bus" -> "Suvarnabhumi Airport" (and other airport points)

This module is dependency-free and easy to extend.
"""

from __future__ import annotations

import re
from typing import Iterable, List
from pathlib import Path
import json


def _canon(s: str) -> str:
    """Canonicalization used only for alias-key lookup."""
    if not s:
        return ""
    s = s.strip().lower()
    s = re.sub(r"\s+", " ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


# Keys are informal user inputs; values are preferred official names/substrings.
ALIASES: dict[str, list[str]] = {
  # ---------------------------
  # Bangkok / Greater Bangkok
  # ---------------------------
  "bangkok": ["Bangkok"],
  "bkk": ["Bangkok"],
  "krung thep": ["Bangkok"],
  "krungthep": ["Bangkok"],
  "dmk": ["Don Mueang"],
  "don mueang": ["Don Mueang"],
  "donmuang": ["Don Mueang"],
  "donmueng": ["Don Mueang"],
  "bkk airport": ["Suvarnabhumi Airport"],
  "suvarnabhumi": ["Suvarnabhumi Airport"],
  "suvarnabhumi airport": ["Suvarnabhumi Airport"],
  "bkk suvarnabhumi": ["Suvarnabhumi Airport"],
  "airport bus": ["Suvarnabhumi Airport Bus Terminal", "Suvarnabhumi Airport", "Don Mueang"],
  "airport": ["Suvarnabhumi Airport", "Don Mueang", "Phuket International Airport", "Chiang Mai International Airport", "Hat Yai International Airport"],
  "mo chit": ["Bangkok Bus Terminal Chatuchak (Mo Chit 2)", "Mo Chit 2", "Chatuchak"],
  "mochit": ["Bangkok Bus Terminal Chatuchak (Mo Chit 2)", "Mo Chit 2", "Chatuchak"],
  "morchit": ["Bangkok Bus Terminal Chatuchak (Mo Chit 2)", "Mo Chit 2", "Chatuchak"],
  "chatuchak terminal": ["Bangkok Bus Terminal Chatuchak (Mo Chit 2)"],
  "north terminal": ["Bangkok Bus Terminal Chatuchak (Mo Chit 2)"],
  "sai tai": ["Bangkok Bus Terminal Southern (Sai Tai Mai)", "Sai Tai Mai", "Southern"],
  "saitai": ["Bangkok Bus Terminal Southern (Sai Tai Mai)", "Sai Tai Mai", "Southern"],
  "sai tai mai": ["Bangkok Bus Terminal Southern (Sai Tai Mai)"],
  "southern terminal": ["Bangkok Bus Terminal Southern (Sai Tai Mai)", "Sai Tai Mai"],
  "ekkamai": ["Bangkok Bus Terminal (Ekkamai)"],
  "eakamai": ["Bangkok Bus Terminal (Ekkamai)"],
  "eastern terminal": ["Bangkok Bus Terminal (Ekkamai)"],
  "victory monument": ["Anusawari", "Victory Monument"],
  "anusa wari": ["Anusawari"],
  "anusa waree": ["Anusawari"],

  # ---------------------------
  # Airports (common IATA-ish)
  # ---------------------------
  "cnx airport": ["Chiang Mai International Airport", "Chiang Mai Airport"],
  "chiang mai airport": ["Chiang Mai International Airport", "Chiang Mai Airport"],
  "hdy airport": ["Hat Yai International Airport", "Hat Yai Airport"],
  "hat yai airport": ["Hat Yai International Airport", "Hat Yai Airport"],
  "uth airport": ["Udon Thani International Airport", "Udon Thani Airport"],
  "ubp airport": ["Ubon Ratchathani Airport", "Ubon Ratchathani"],
  "urt airport": ["Surat Thani Airport", "Suratthani Airport"],
  "nst airport": ["Nakhon Si Thammarat Airport", "Nakhon Si Thammarat"],
  "kbv airport": ["Krabi Airport", "Krabi"],
  "hkt airport": ["Phuket International Airport", "Phuket Airport"],
  "phuket airport": ["Phuket International Airport", "Phuket Airport"],
  "usm airport": ["Koh Samui Airport", "Koh Samui"],

  # ---------------------------
  # Chiang Mai / North
  # ---------------------------
  "chiang mai": ["Chiang Mai"],
  "cnx": ["Chiang Mai"],
  "arcade": ["Chiang Mai Bus Terminal 3 (Arcade)", "Chiang Mai Bus Terminal"],
  "arcade terminal": ["Chiang Mai Bus Terminal 3 (Arcade)"],
  "chiang rai": ["Chiang Rai"],
  "cei": ["Chiang Rai"],
  "chiang rai terminal": ["Chiang Rai Bus Terminal 2", "Chiang Rai Bus Terminal"],
  "pai": ["Pai"],
  "mae hong son": ["Mae Hong Son"],
  "mae sot": ["Mae Sot"],
  "lampang": ["Lampang"],
  "lamphun": ["Lamphun"],
  "nan": ["Nan"],
  "phrae": ["Phrae"],
  "uttaradit": ["Uttaradit"],

  # ---------------------------
  # Isan / Northeast
  # ---------------------------
  "khon kaen": ["Khon Kaen"],
  "kkn": ["Khon Kaen"],
  "udon": ["Udon Thani"],
  "udon thani": ["Udon Thani"],
  "ubon": ["Ubon Ratchathani"],
  "ubon ratchathani": ["Ubon Ratchathani"],
  "nakhon ratchasima": ["Nakhon Ratchasima"],
  "korat": ["Nakhon Ratchasima"],
  "buriram": ["Buri Ram"],
  "surin": ["Surin"],
  "roi et": ["Roi Et"],
  "sakonnakhon": ["Sakon Nakhon"],
  "sakon nakhon": ["Sakon Nakhon"],
  "nong khai": ["Nong Khai"],
  "loei": ["Loei"],
  "kalasin": ["Kalasin"],
  "yasothon": ["Yasothon"],
  "mukdahan": ["Mukdahan"],
  "nakhon phanom": ["Nakhon Phanom"],
  "bueng kan": ["Bueng Kan"],

  # ---------------------------
  # East / Pattaya / Trat
  # ---------------------------
  "pattaya": ["Pattaya"],
  "north pattaya": ["North Pattaya"],
  "south pattaya": ["South Pattaya"],
  "rayong": ["Rayong"],
  "trat": ["Trat"],
  "koh chang": ["Koh Chang", "Trat"],
  "ban phe": ["Ban Phe Pier", "Ban Phe"],
  "ban phe pier": ["Ban Phe Pier"],

  # ---------------------------
  # West / Central (tourist)
  # ---------------------------
  "kanchanaburi": ["Kanchanaburi"],
  "kanchanaburi bus": ["Kanchanaburi Bus Terminal", "Kanchanaburi"],
  "ayutthaya": ["Phra Nakhon Si Ayutthaya"],
  "phra nakhon si ayutthaya": ["Phra Nakhon Si Ayutthaya"],
  "lopburi": ["Lop Buri"],
  "nakhon pathom": ["Nakhon Pathom"],
  "suphan buri": ["Suphan Buri"],
  "saraburi": ["Saraburi"],

  # ---------------------------
  # Gulf / South (key hubs)
  # ---------------------------
  "hua hin": ["Hua Hin"],
  "huahin": ["Hua Hin"],
  "phetchaburi": ["Phetchaburi"],
  "prachuap": ["Prachuap Khiri Khan"],
  "prachuap khiri khan": ["Prachuap Khiri Khan"],
  "chumphon": ["Chumphon"],
  "ranong": ["Ranong"],
  "surat": ["Surat Thani"],
  "surat thani": ["Surat Thani"],
  "donsak": ["Don Sak", "Donsak Pier (Seatran Ferry)"],
  "don sak": ["Don Sak", "Donsak Pier (Seatran Ferry)"],
  "donsak pier": ["Donsak Pier (Seatran Ferry)"],
  "koh samui": ["Koh Samui"],
  "samui": ["Koh Samui"],
  "koh phangan": ["Koh Phangan"],
  "phangan": ["Koh Phangan"],
  "koh tao": ["Koh Tao"],
  "tao": ["Koh Tao"],

  "hat yai": ["Hat Yai"],
  "hdy": ["Hat Yai"],
  "songkhla": ["Songkhla"],
  "trang": ["Trang"],
  "krabi": ["Krabi"],
  "phang nga": ["Phangnga"],
  "phangnga": ["Phangnga"],
  "phuket": ["Phuket"],
  "hkt": ["Phuket"],
  "rawai": ["Rawai"],

  # Border / popular intl names (if in your BusX catalog)
  "poipet": ["Poipet International Border Checkpoint", "Poipet"],
  "vientiane": ["Vientiane"],
  "phnom penh": ["Phnom Penh"],
  "siem reap": ["Siem Reap"],
}


def expand_queries(user_text: str) -> List[str]:
    """Return preferred query expansions for a user input."""
    q = (user_text or "").strip()
    cq = _canon(q)
    if not cq:
        return []

    expansions: List[str] = []

    # Exact alias match
    for key, targets in ALIASES.items():
        if _canon(key) == cq:
            if isinstance(targets, str):
                expansions.append(targets)
            else:
                expansions.extend(list(targets))
            break

    # Heuristic: if the user mentions "airport" inside a longer phrase
    if "airport" in cq and cq != _canon("airport"):
        expansions.extend(ALIASES.get("airport", []))

    # Dedupe while preserving order
    seen = set()
    out: List[str] = []
    for x in expansions:
        cx = _canon(x)
        if cx and cx not in seen:
            seen.add(cx)
            out.append(x)
    return out


def iter_alias_targets(user_text: str) -> Iterable[str]:
    """Yield alias targets (if any)."""
    yield from expand_queries(user_text)

# EXTRA_ALIASES_ADDED
EXTRA_ALIASES = {
    "BKK": "Bangkok",
    "DMK": "Bangkok",
    "HKT": "Phuket",
    "CNX": "Chiang Mai",
    "KBV": "Krabi",
    "USM": "Koh Samui",
    "bkk": "Bangkok",
    "hkt": "Phuket",
    "bankok": "Bangkok",
    "bangok": "Bangkok",
    "bagnkok": "Bangkok",
    "puket": "Phuket",
    "phukat": "Phuket",
    "phukett": "Phuket",
    "phukettt": "Phuket",
}

try:
    ALIASES.update(EXTRA_ALIASES)
except Exception:
    pass


# ---------------------------
# Auto-add Thailand city/province names from from_keywords.json
# This ensures stop lookup can match any Thai city name even if it wasn't
# manually added above.
# ---------------------------

def _load_th_city_aliases() -> dict[str, list[str]]:
    try:
        here = Path(__file__).resolve()
        root = here.parents[3]  # .../ChatBot_V11
        fp = root / "from_keywords.json"
        if not fp.exists():
            return {}
        data = json.loads(fp.read_text(encoding="utf-8"))
        items = data.get("data") or []
        out: dict[str, list[str]] = {}
        for it in items:
            name = (it or {}).get("keyword_name") or (it or {}).get("state_province_name")
            name = (name or "").strip()
            if not name:
                continue
            k1 = _canon(name)
            k2 = k1.replace(" ", "")
            if k1:
                out.setdefault(k1, []).append(name)
            if k2 and k2 != k1:
                out.setdefault(k2, []).append(name)
        return out
    except Exception:
        return {}


try:
    ALIASES.update(_load_th_city_aliases())
except Exception:
    pass
