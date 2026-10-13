"""Session persistence: in-process by default, Redis when configured.

Both backends share one interface so `main.py` never branches on which is
active. The in-memory store is process-local and therefore single-worker only;
set `REDIS_URL` before scaling out.
"""

from __future__ import annotations

import asyncio
import logging
import time
from abc import ABC, abstractmethod
from typing import Final

from .config import Settings, get_settings
from .schemas import SessionState

logger = logging.getLogger(__name__)

_KEY_PREFIX: Final = "saa:session:"


class SessionStore(ABC):
    """Async key/value store for `SessionState`."""

    @abstractmethod
    async def get(self, session_id: str) -> SessionState | None: ...

    @abstractmethod
    async def save(self, state: SessionState) -> None: ...

    @abstractmethod
    async def delete(self, session_id: str) -> None: ...

    async def load_or_create(self, session_id: str | None) -> SessionState:
        if session_id:
            existing = await self.get(session_id)
            if existing is not None:
                return existing
            # Honour a client-supplied id even on a miss (expired TTL, restart)
            # so the browser's id and the server's stay in sync.
            return SessionState(session_id=session_id)
        return SessionState()

    async def close(self) -> None:  # pragma: no cover - default no-op
        return None


class InMemorySessionStore(SessionStore):
    """Dict-backed store with lazy TTL eviction. Suitable for one worker."""

    def __init__(self, ttl_seconds: int) -> None:
        self._ttl = ttl_seconds
        self._data: dict[str, tuple[float, SessionState]] = {}
        self._lock = asyncio.Lock()
        self._last_eviction = 0.0

    async def get(self, session_id: str) -> SessionState | None:
        async with self._lock:
            entry = self._data.get(session_id)
            if entry is None:
                return None
            expires_at, state = entry
            if expires_at <= time.time():
                self._data.pop(session_id, None)
                return None
        # Copy outside the lock to minimize lock hold duration and eliminate
        # cross-request contention during deep serialization.
        return state.model_copy(deep=True)

    async def save(self, state: SessionState) -> None:
        # Pre-copy state outside the lock: model serialization is CPU-bound
        # and should not stall other concurrent coroutines.
        copied = state.model_copy(deep=True)
        expires_at = time.time() + self._ttl
        async with self._lock:
            self._evict_expired()
            self._data[state.session_id] = (expires_at, copied)

    async def delete(self, session_id: str) -> None:
        async with self._lock:
            self._data.pop(session_id, None)

    def _evict_expired(self) -> None:
        now = time.time()
        # Throttle full sweeps to at most once per minute rather than iterating
        # the entire dictionary on every write; individual keys are already
        # evicted lazily on access in get().
        if now - self._last_eviction < 60.0:
            return
        self._last_eviction = now
        for key in [k for k, (exp, _) in self._data.items() if exp <= now]:
            self._data.pop(key, None)


class RedisSessionStore(SessionStore):
    """Redis-backed store; state is serialised as JSON with a rolling TTL."""

    def __init__(self, url: str, ttl_seconds: int) -> None:
        from redis.asyncio import ConnectionPool, Redis  # imported lazily: optional dependency

        # Configure an explicit connection pool with health checks and aggressive
        # timeouts so dropped connections or network blips fail fast instead of
        # blocking async event loops.
        pool = ConnectionPool.from_url(
            url,
            decode_responses=True,
            max_connections=50,
            socket_timeout=3.0,
            socket_connect_timeout=2.0,
            socket_keepalive=True,
            health_check_interval=30,
        )
        self._redis = Redis(connection_pool=pool)
        self._ttl = ttl_seconds

    async def get(self, session_id: str) -> SessionState | None:
        try:
            raw = await self._redis.get(_KEY_PREFIX + session_id)
        except Exception:
            logger.exception("Redis GET failed for session %s", session_id)
            return None
        if raw is None:
            return None
        try:
            return SessionState.model_validate_json(raw)
        except ValueError:
            # A schema change can strand old payloads; drop rather than 500.
            logger.warning("Discarding unreadable session payload %s", session_id)
            await self.delete(session_id)
            return None

    async def save(self, state: SessionState) -> None:
        try:
            await self._redis.set(
                _KEY_PREFIX + state.session_id,
                state.model_dump_json(),
                ex=self._ttl,
            )
        except Exception:
            logger.exception("Redis SET failed for session %s", state.session_id)

    async def delete(self, session_id: str) -> None:
        try:
            await self._redis.delete(_KEY_PREFIX + session_id)
        except Exception:
            logger.exception("Redis DEL failed for session %s", session_id)

    async def close(self) -> None:
        await self._redis.aclose()


def build_session_store(settings: Settings | None = None) -> SessionStore:
    """Pick a backend from configuration, falling back to memory on failure."""
    settings = settings or get_settings()
    if settings.redis_url:
        try:
            return RedisSessionStore(settings.redis_url, settings.session_ttl_seconds)
        except ImportError:
            logger.warning(
                "REDIS_URL is set but redis-py is not installed; "
                "falling back to in-memory sessions."
            )
    return InMemorySessionStore(settings.session_ttl_seconds)
