# app/utils/env.py
"""Shared environment-variable helpers.

Centralizes the _env_* utilities that were previously duplicated across
main.py and orchestrator.py.
"""
from __future__ import annotations

import os


def env_str(name: str, default: str) -> str:
    v = (os.getenv(name, default) or default).strip()
    return v or default


def env_int(name: str, default: int) -> int:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except Exception:
        return default


def env_int_required(name: str) -> int:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        raise RuntimeError(f"{name} missing in .env")
    try:
        return int(raw)
    except Exception as e:
        raise RuntimeError(f"{name} must be an integer, got '{raw}'") from e


def env_float(name: str, default: float) -> float:
    raw = (os.getenv(name, "") or "").strip()
    if not raw:
        return default
    try:
        return float(raw)
    except Exception:
        return default


def env_bool(name: str, default: bool) -> bool:
    raw = (os.getenv(name, "") or "").strip().lower()
    if not raw:
        return default
    if raw in {"1", "true", "t", "yes", "y", "on"}:
        return True
    if raw in {"0", "false", "f", "no", "n", "off"}:
        return False
    return default
