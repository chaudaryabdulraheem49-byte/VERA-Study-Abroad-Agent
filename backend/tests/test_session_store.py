import asyncio
import time
from unittest.mock import AsyncMock, patch

import pytest

from app.schemas import SessionState
from app.session_store import InMemorySessionStore, RedisSessionStore, build_session_store


@pytest.mark.asyncio
async def test_in_memory_store_lifecycle():
    store = InMemorySessionStore(ttl_seconds=2)
    state = SessionState(session_id="test-1")
    state.slots.full_name = "Alice"

    # Save
    await store.save(state)

    # Get
    retrieved = await store.get("test-1")
    assert retrieved is not None
    assert retrieved.slots.full_name == "Alice"

    # Ensure deep copy: mutating retrieved does not affect stored state
    retrieved.slots.full_name = "Bob"
    fresh = await store.get("test-1")
    assert fresh is not None
    assert fresh.slots.full_name == "Alice"

    # Delete
    await store.delete("test-1")
    assert await store.get("test-1") is None


@pytest.mark.asyncio
async def test_in_memory_store_expiration():
    store = InMemorySessionStore(ttl_seconds=1)
    state = SessionState(session_id="test-expire")
    await store.save(state)

    # Force expiration
    store._data["test-expire"] = (time.time() - 1, state)

    # Lazy eviction on get
    assert await store.get("test-expire") is None
    assert "test-expire" not in store._data


@pytest.mark.asyncio
async def test_in_memory_store_throttled_eviction():
    store = InMemorySessionStore(ttl_seconds=10)
    state1 = SessionState(session_id="s1")
    state2 = SessionState(session_id="s2")

    await store.save(state1)
    await store.save(state2)

    # Artificially expire s1
    store._data["s1"] = (time.time() - 10, state1)

    # Save s3 within the 60s throttle window - s1 should not be swept yet
    state3 = SessionState(session_id="s3")
    await store.save(state3)
    assert "s1" in store._data

    # Force last_eviction to be older than 60s
    store._last_eviction = time.time() - 61.0
    state4 = SessionState(session_id="s4")
    await store.save(state4)
    # Now s1 should be evicted during save
    assert "s1" not in store._data
    assert "s2" in store._data


@pytest.mark.asyncio
async def test_load_or_create():
    store = InMemorySessionStore(ttl_seconds=60)

    # With None id
    s_new = await store.load_or_create(None)
    assert s_new.session_id is not None

    # With missing client id
    s_client = await store.load_or_create("custom-id")
    assert s_client.session_id == "custom-id"

    # With existing id
    s_client.slots.full_name = "Charlie"
    await store.save(s_client)
    s_existing = await store.load_or_create("custom-id")
    assert s_existing.slots.full_name == "Charlie"


@pytest.mark.asyncio
async def test_redis_session_store_mocked():
    with patch("redis.asyncio.ConnectionPool.from_url") as mock_pool, \
         patch("redis.asyncio.Redis") as mock_redis_cls:
        mock_redis = AsyncMock()
        mock_redis_cls.return_value = mock_redis

        store = RedisSessionStore("redis://localhost:6379/0", ttl_seconds=3600)
        mock_pool.assert_called_once()
        assert mock_pool.call_args[1]["socket_timeout"] == 3.0
        assert mock_pool.call_args[1]["socket_connect_timeout"] == 2.0
        assert mock_pool.call_args[1]["health_check_interval"] == 30

        # Save
        state = SessionState(session_id="r1")
        await store.save(state)
        mock_redis.set.assert_awaited_once()

        # Get
        mock_redis.get.return_value = state.model_dump_json()
        loaded = await store.get("r1")
        assert loaded is not None
        assert loaded.session_id == "r1"

        # Delete
        await store.delete("r1")
        mock_redis.delete.assert_awaited_once_with("saa:session:r1")

        # Close
        await store.close()
        mock_redis.aclose.assert_awaited_once()
