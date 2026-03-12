# app/utils/canonical.py
from __future__ import annotations

from dataclasses import dataclass
import re
import unicodedata
from difflib import SequenceMatcher
from typing import Any, Dict, Iterable, List, Optional, Sequence

# --- public types -------------------------------------------------------------

@dataclass(frozen=True)
class Candidate:
    keyword_id: str
    score: float
    keyword_name: Optional[str] = None
    row: Optional[Dict[str, Any]] = None


# --- normalization ------------------------------------------------------------

_THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

# map common punctuation variants to spaces so tokenization works
_PUNCT_RE = re.compile(r"[^\w\s\u0E00-\u0E7F]+", flags=re.UNICODE)  # keep Thai block
_WS_RE = re.compile(r"\s+", flags=re.UNICODE)

def canonical_text(s: str) -> str:
    """
    Dependency-free canonicalization:
    - Unicode normalize (NFKD) and remove combining marks (accent stripping)
    - lowercase
    - normalize Thai digits to Latin digits
    - replace punctuation with spaces
    - collapse whitespace
    Works for Thai without transliteration.
    """
    if not s:
        return ""

    s = s.strip()
    s = s.translate(_THAI_DIGITS)

    # NFKD + strip combining marks (accents)
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))

    s = s.lower()

    # Convert punctuation to spaces (keep Thai letters)
    s = _PUNCT_RE.sub(" ", s)

    # Collapse whitespace
    s = _WS_RE.sub(" ", s).strip()
    return s


def _tokens(s: str) -> List[str]:
    s = canonical_text(s)
    if not s:
        return []
    return [t for t in s.split(" ") if t]


def _ratio(a: str, b: str) -> float:
    # stdlib fuzzy; safe & dependency-free
    if not a or not b:
        return 0.0
    return SequenceMatcher(a=a, b=b).ratio()


# --- scoring ------------------------------------------------------------------

def _score(query_c: str, query_tokens: Sequence[str], name_c: str, name_tokens: Sequence[str]) -> float:
    if not query_c or not name_c:
        return 0.0

    qset = set(query_tokens)
    nset = set(name_tokens)

    # token overlap (handles Thai phrases with spaces; for Thai without spaces overlap is weaker,
    # but contains/prefix/ratio still help)
    overlap = 0.0
    if qset and nset:
        overlap = len(qset & nset) / max(1, len(qset))

    # contains / prefix bonuses
    contains = 1.0 if (query_c in name_c or name_c in query_c) else 0.0
    prefix = 1.0 if (name_c.startswith(query_c) or query_c.startswith(name_c)) else 0.0

    # lightweight fuzzy backup
    fuzz = _ratio(query_c, name_c)

    # weighted blend
    # overlap does most work when tokenizable; contains/prefix handle Thai + mixed scripts;
    # fuzz catches minor typos
    score = (
        0.55 * overlap +
        0.20 * contains +
        0.15 * prefix +
        0.10 * fuzz
    )
    return float(score)


def canonicalize(
    query: str,
    rows: List[Dict[str, Any]],
    top_k: int = 5,
    min_score: float = 0.35,
    *,
    id_key: str = "keyword_id",
    name_key: str = "keyword_name",
    extra_name_keys: Optional[Sequence[str]] = None,
) -> List[Candidate]:
    """
    Rank `rows` against `query` using dependency-free canonical scoring.
    - rows are typically your BusX keyword rows
    - expects keyword id/name keys (configurable)
    - returns sorted candidates (desc score)
    """
    query_c = canonical_text(query)
    qtoks = _tokens(query_c)

    if not query_c or not rows:
        return []

    keys = [name_key]
    if extra_name_keys:
        keys.extend(list(extra_name_keys))

    scored: List[Candidate] = []
    for r in rows:
        kid = str(r.get(id_key, "")).strip()
        if not kid:
            continue

        # combine possible names into one string for matching (no alias list; just use whatever BusX provides)
        names: List[str] = []
        for k in keys:
            v = r.get(k)
            if isinstance(v, str) and v.strip():
                names.append(v.strip())
        if not names:
            continue

        # best score among provided name fields
        best = 0.0
        best_name = None
        for nm in names:
            nm_c = canonical_text(nm)
            ntoks = _tokens(nm_c)
            s = _score(query_c, qtoks, nm_c, ntoks)
            if s > best:
                best = s
                best_name = nm

        if best >= min_score:
            scored.append(Candidate(keyword_id=kid, score=best, keyword_name=best_name, row=r))

    scored.sort(key=lambda c: c.score, reverse=True)
    return scored[: max(1, int(top_k))]