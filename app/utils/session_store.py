# app/utils/session_store.py
"""Session storage abstraction.

Default implementation: in-memory (single-process, not suitable for
multi-worker or persistent deployments).

To add Redis or DB persistence, subclass SessionStore and override
get() / set() / delete(), then pass your implementation to Orchestrator.

Usage:
    from app.utils.session_store import InMemorySessionStore
    store = InMemorySessionStore()
    store.set("user1", state_dict)
    state = store.get("user1")
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class SessionStore:
    """Abstract base class for session storage."""

    def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError

    def set(self, user_id: str, state: Dict[str, Any]) -> None:
        raise NotImplementedError

    def delete(self, user_id: str) -> None:
        raise NotImplementedError


class InMemorySessionStore(SessionStore):
    """In-memory session store.

    WARNING: Sessions are lost on process restart and NOT shared across
    multiple workers/instances. Suitable for development and single-process
    deployments only. For production with multiple workers, use a
    persistent store (Redis, database, etc.).
    """

    def __init__(self) -> None:
        self._store: Dict[str, Dict[str, Any]] = {}
        logger.warning(
            "InMemorySessionStore: sessions are stored in RAM only. "
            "All sessions will be lost on restart. "
            "For multi-worker or persistent deployments, use a Redis/DB-backed store."
        )

    def get(self, user_id: str) -> Optional[Dict[str, Any]]:
        return self._store.get(user_id)

    def set(self, user_id: str, state: Dict[str, Any]) -> None:
        self._store[user_id] = state

    def delete(self, user_id: str) -> None:
        self._store.pop(user_id, None)
