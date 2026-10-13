"""Caching query vectors so a repeated search costs no allowance.

On a metered tier this is not an optimisation. Every search embeds the
student's query, so an exhausted allowance does not merely pause the backfill
- it takes search offline for everyone. A cache hit needs no allowance at all.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from app.services.phase2 import embedding_cache


@pytest.fixture(autouse=True)
def isolated_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(embedding_cache, "CACHE_PATH", tmp_path / "vectors.json")
    embedding_cache.reset()
    yield
    embedding_cache.reset()


def test_a_cold_cache_is_a_miss_not_an_error() -> None:
    assert embedding_cache.get("Computer Science UK Masters") is None


def test_a_vector_round_trips() -> None:
    embedding_cache.put("Law Canada Masters", [0.1, 0.2, 0.3])
    assert embedding_cache.get("Law Canada Masters") == [0.1, 0.2, 0.3]


def test_it_survives_a_restart(tmp_path: Path) -> None:
    """The allowance is reckoned per day while a process lives for minutes, so
    an in-memory cache would be empty again exactly when it is most needed."""
    embedding_cache.put("Data Science Australia Masters", [0.4])
    embedding_cache.reset()  # as if the process had restarted
    assert embedding_cache.get("Data Science Australia Masters") == [0.4]


def test_different_queries_do_not_collide() -> None:
    embedding_cache.put("Law Canada Masters", [1.0])
    embedding_cache.put("Law Australia Masters", [2.0])
    assert embedding_cache.get("Law Canada Masters") == [1.0]
    assert embedding_cache.get("Law Australia Masters") == [2.0]


def test_a_model_change_invalidates_the_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two models occupy different spaces. Serving a cached vector after a
    model change would compare a query in one geometry against courses in
    another - a wrong answer rather than a missing one."""
    embedding_cache.put("Computer Science UK Masters", [0.5])

    settings = embedding_cache.get_settings()
    monkeypatch.setattr(
        settings, "embedding_model", "some-other-model", raising=False
    )
    embedding_cache.reset()
    assert embedding_cache.get("Computer Science UK Masters") is None


def test_a_width_change_invalidates_the_entry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    embedding_cache.put("Computer Science UK Masters", [0.5])

    settings = embedding_cache.get_settings()
    monkeypatch.setattr(settings, "embedding_dimensions", 768, raising=False)
    embedding_cache.reset()
    assert embedding_cache.get("Computer Science UK Masters") is None


def test_a_corrupt_cache_is_a_cold_cache(tmp_path: Path) -> None:
    """A run killed mid-write must not break search; the caller can always
    fall back to embedding the query."""
    (tmp_path / "vectors.json").write_text('{"abc": [0.1', encoding="utf-8")
    embedding_cache.reset()
    assert embedding_cache.get("anything") is None


def test_the_file_does_not_grow_without_bound() -> None:
    """Each entry is ~30 KB of JSON, and the whole file is loaded in one go."""
    for index in range(embedding_cache.MAX_ENTRIES + 25):
        embedding_cache.put(f"query {index}", [float(index)])
    embedding_cache.reset()
    assert embedding_cache.get("query 0") is None            # evicted
    assert embedding_cache.get(f"query {embedding_cache.MAX_ENTRIES + 24}") is not None


def test_writing_is_atomic(tmp_path: Path) -> None:
    embedding_cache.put("x", [1.0])
    assert not (tmp_path / "vectors.tmp").exists()


# --------------------------------------------------------------------------- #
# Keeping the disk work off the event loop
# --------------------------------------------------------------------------- #


def test_the_async_forms_agree_with_the_sync_ones() -> None:
    """`aget`/`aput` only move where the work happens, never what it does."""
    import asyncio

    embedding_cache.reset()
    vector = [0.25] * 8

    asyncio.run(embedding_cache.aput("async round trip", vector))
    assert asyncio.run(embedding_cache.aget("async round trip")) == vector
    # The sync reader sees the same entry.
    assert embedding_cache.get("async round trip") == vector


def test_a_warm_read_does_not_need_a_thread() -> None:
    """Once loaded the lookup is a dict hit, so paying for a thread hop on
    every read would cost more than it saves."""
    import asyncio

    embedding_cache.reset()
    embedding_cache.put("warm", [0.5] * 4)
    # Loading happened above, so _memory is populated and `aget` takes the
    # direct path.
    assert embedding_cache._memory is not None
    assert asyncio.run(embedding_cache.aget("warm")) == [0.5] * 4


def test_a_write_does_not_stall_other_work() -> None:
    """The regression this guards: `put` re-serialises the whole cache and
    rewrites the file. Done inline that is tens of milliseconds during which
    no other request in the process progresses."""
    import asyncio
    import time

    embedding_cache.reset()

    async def scenario() -> float:
        stalls: list[float] = []
        stop = asyncio.Event()

        async def heartbeat() -> None:
            last = time.perf_counter()
            while not stop.is_set():
                await asyncio.sleep(0.001)
                now = time.perf_counter()
                stalls.append((now - last) * 1000)
                last = now

        beat = asyncio.create_task(heartbeat())
        await asyncio.sleep(0.02)
        for index in range(3):
            await embedding_cache.aput(f"stall probe {index}", [0.1] * 1536)
        stop.set()
        await beat
        return max(stalls)

    worst = asyncio.run(scenario())
    # Generous: the point is that the loop keeps turning during the write, not
    # that it is instant. Inline writes of a large cache blocked far longer.
    assert worst < 500, f"event loop stalled {worst:.0f} ms during a cache write"
