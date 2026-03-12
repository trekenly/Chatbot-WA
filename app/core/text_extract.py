"""Backwards-compatible wrapper.

Historically, main.py imported `extract_from_to` from this module.
The real implementation now lives in `app.core.parsing`.
"""

from __future__ import annotations

from typing import Optional, Tuple

from app.core.parsing import extract_from_to as _extract


def extract_from_to(text: str) -> Tuple[Optional[str], Optional[str]]:
    return _extract(text)
