from __future__ import annotations

import os
import time
from typing import Any, Optional

import httpx

from app.busx.endpoints import ACCESS_TOKEN, REFRESH_TOKEN


class TokenCache:
    def __init__(self) -> None:
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self.expiry_ts: Optional[float] = None  # epoch seconds

    def valid(self) -> bool:
        # keep a small safety margin
        return bool(self.access_token and self.expiry_ts and time.time() < (self.expiry_ts - 30))


_cache = TokenCache()


def _api_key() -> str:
    v = os.getenv("BUSX_API_KEY", "").strip()
    if not v:
        raise RuntimeError("BUSX_API_KEY is missing. Put it in .env and restart uvicorn.")
    return v


def _api_secret() -> str:
    v = os.getenv("BUSX_API_SECRET", "").strip()
    if not v:
        raise RuntimeError("BUSX_API_SECRET is missing. Put it in .env and restart uvicorn.")
    return v


async def get_access_token(client: httpx.AsyncClient) -> str:
    """
    BusX token response observed:
      {"success": true, "message": null, "data": {"access_token": "...", "expires": 1769316606, "refresh_token": "..."}}

    - Caches token in-memory.
    - Uses refresh_token when available.
    """
    if _cache.valid():
        return _cache.access_token  # type: ignore

    # 1) Try refresh first if we have refresh_token
    if _cache.refresh_token:
        try:
            r = await client.post(
                REFRESH_TOKEN,
                data={"api_key": _api_key(), "refresh_token": _cache.refresh_token},
                timeout=20,
            )
            r.raise_for_status()
            data = r.json()
            print("BUSX REFRESH RAW (REDACTED):", _redact(data))
            _apply_token_response(data)
            if _cache.valid():
                return _cache.access_token  # type: ignore
        except Exception:
            # Fall through to new token
            pass

    # 2) New token
    r = await client.post(
        ACCESS_TOKEN,
        data={"api_key": _api_key(), "api_secret": _api_secret()},
        timeout=20,
    )
    r.raise_for_status()
    data = r.json()
    print("BUSX TOKEN RAW (REDACTED):", _redact(data))
    _apply_token_response(data)

    if not _cache.access_token:
        raise RuntimeError(f"Token response missing access_token. Raw (redacted): {_redact(data)}")

    return _cache.access_token


def _apply_token_response(resp: dict[str, Any]) -> None:
    """
    Apply token response to cache.
    Handles both:
      - nested: {"data": {"access_token": "...", "expires": 1769..., "refresh_token": "..."}}
      - flat:   {"access_token": "...", "expires_in": 3600, ...}
    """
    # Prefer nested "data" dict if present
    data = resp.get("data")
    root: dict[str, Any] = data if isinstance(data, dict) else resp

    access = root.get("access_token") or root.get("token") or root.get("access")
    refresh = root.get("refresh_token") or root.get("refresh")

    _cache.access_token = str(access) if access else None
    if refresh:
        _cache.refresh_token = str(refresh)

    # BusX uses epoch "expires" (seconds)
    expires_epoch = root.get("expires")
    if expires_epoch is not None:
        try:
            _cache.expiry_ts = float(expires_epoch)
            return
        except Exception:
            pass

    # Fallback to expires_in seconds
    expires_in = root.get("expires_in") or root.get("expiresIn")
    if expires_in is None:
        expires_in = 3600
    try:
        expires_in = int(expires_in)
    except Exception:
        expires_in = 3600
    _cache.expiry_ts = time.time() + expires_in


def _redact(obj: Any) -> Any:
    """
    Redact secrets/tokens from logs and error messages.
    """
    if isinstance(obj, dict):
        out: dict[str, Any] = {}
        for k, v in obj.items():
            lk = str(k).lower()
            if "token" in lk or "secret" in lk or lk in {"api_key", "api_secret"}:
                out[k] = "***REDACTED***"
            else:
                out[k] = _redact(v)
        return out
    if isinstance(obj, list):
        return [_redact(x) for x in obj]
    return obj
