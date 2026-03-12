"""Session state store for messaging channels.

Web clients carry state client-side (in the React component).
Messaging channels (WhatsApp, LINE, Messenger) are stateless, so we keep
server-side sessions here.

Two backends:
  - MemoryStore  : default, good for single-process development / tests
  - RedisStore   : recommended for production (install redis + set REDIS_URL)

Usage:
    store = get_store()
    state = await store.get(user_id)         # -> dict or {}
    await store.set(user_id, new_state)
    await store.delete(user_id)
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict

_DEFAULT_TTL = 60 * 60 * 6   # 6 hours


class MemoryStore:
    """In-process dict store (no persistence, single-process only)."""

    def __init__(self) -> None:
        self._data: Dict[str, Dict[str, Any]] = {}

    async def get(self, user_id: str) -> Dict[str, Any]:
        return dict(self._data.get(user_id) or {})

    async def set(self, user_id: str, state: Dict[str, Any], ttl: int = _DEFAULT_TTL) -> None:
        self._data[user_id] = dict(state or {})

    async def delete(self, user_id: str) -> None:
        self._data.pop(user_id, None)


class RedisStore:
    """Redis-backed store (requires `pip install redis`)."""

    def __init__(self, url: str) -> None:
        import redis.asyncio as aioredis  # type: ignore
        self._redis = aioredis.from_url(url, decode_responses=True)

    async def get(self, user_id: str) -> Dict[str, Any]:
        try:
            raw = await self._redis.get(f"busx:session:{user_id}")
            return json.loads(raw) if raw else {}
        except Exception:
            return {}

    async def set(self, user_id: str, state: Dict[str, Any], ttl: int = _DEFAULT_TTL) -> None:
        try:
            await self._redis.setex(
                f"busx:session:{user_id}",
                ttl,
                json.dumps(state or {}, ensure_ascii=False),
            )
        except Exception:
            pass

    async def delete(self, user_id: str) -> None:
        try:
            await self._redis.delete(f"busx:session:{user_id}")
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------

_store_instance: MemoryStore | RedisStore | None = None


def get_store() -> MemoryStore | RedisStore:
    global _store_instance
    if _store_instance is None:
        redis_url = (os.getenv("REDIS_URL") or "").strip()
        if redis_url:
            try:
                _store_instance = RedisStore(redis_url)
            except Exception:
                _store_instance = MemoryStore()
        else:
            _store_instance = MemoryStore()
    return _store_instance
