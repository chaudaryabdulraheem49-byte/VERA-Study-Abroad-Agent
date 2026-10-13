"""Remember query embeddings, so repeating a search costs nothing.

Search queries repeat heavily and course syllabi do not. Students arrive with
the same few dozen subjects - "Computer Science Australia Masters" is asked
over and over - while every course is embedded exactly once. So caching is
worth it on one side of the pipeline and pointless on the other, and this is
used only by the search path.

On a metered free tier that is not an optimisation, it is what keeps the
feature working. Every search embeds the student's query, so an exhausted
allowance does not merely pause the backfill: it takes search offline for
everyone. A cache hit needs no allowance at all.

Stored on disk rather than in memory because the allowance is reckoned per
day while a process lives for minutes - an in-memory cache would be empty
again after every restart, which is exactly when it is most needed.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Final

from ...config import get_settings

logger = logging.getLogger(__name__)

CACHE_PATH: Final = Path(__file__).resolve().parents[3] / "data" / "query_vectors.json"

# Entries are ~1536 floats each, so roughly 30 KB of JSON apiece. A few hundred
# distinct queries is a realistic ceiling for one deployment and keeps the file
# small enough to load in one go.
MAX_ENTRIES: Final = 500

_lock = threading.Lock()
_memory: dict[str, list[float]] | None = None


def _key(text: str) -> str:
    """Identify a vector by its text *and* the model that produced it.

    Two models occupy different spaces, so serving a cached vector after a
    model change would silently compare a query in one geometry against
    courses in another - a wrong answer rather than a missing one.
    """
    settings = get_settings()
    material = f"{settings.embedding_model}|{settings.embedding_dimensions}|{text}"
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _load() -> dict[str, list[float]]:
    global _memory
    if _memory is not None:
        return _memory
    try:
        _memory = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        # A missing or corrupt cache is a cold cache, never an error: the
        # caller can always fall back to embedding the query.
        _memory = {}
    return _memory


def get(text: str) -> list[float] | None:
    with _lock:
        return _load().get(_key(text))


def put(text: str, vector: list[float]) -> None:
    with _lock:
        cache = _load()
        cache[_key(text)] = vector
        if len(cache) > MAX_ENTRIES:
            # Oldest-inserted first. Python dicts preserve insertion order, so
            # this is a plain FIFO - crude, but the working set here is small
            # and a true LRU would mean tracking access times on every read.
            for stale in list(cache)[: len(cache) - MAX_ENTRIES]:
                cache.pop(stale, None)
        try:
            CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
            temporary = CACHE_PATH.with_suffix(".tmp")
            temporary.write_text(json.dumps(cache), encoding="utf-8")
            temporary.replace(CACHE_PATH)
        except OSError as exc:
            # A read-only filesystem must not break search; the in-memory copy
            # still serves this process.
            logger.warning("Could not write the query vector cache: %s", exc)


async def aget(text: str) -> list[float] | None:
    """`get`, without stalling the event loop on a cold read.

    After the first call the lookup is a dict hit and costs nothing, so only
    the load is worth moving off the loop. That load deserialises the whole
    file - ~920 KB and about 25 ms here - and every other request in the
    process waits through it.
    """
    if _memory is not None:  # already warm: a plain dict lookup
        return get(text)
    return await asyncio.to_thread(get, text)


async def aput(text: str, vector: list[float]) -> None:
    """`put`, without stalling the event loop on the write.

    This is the one that actually hurt. Every miss re-serialises the entire
    cache and rewrites the file - measured at ~40 ms of pure CPU on the event
    loop, during which nothing else in the API progresses. Awaiting it in a
    worker thread keeps the cost but stops it being everyone's cost.
    """
    await asyncio.to_thread(put, text, vector)


def reset() -> None:
    """Drop the in-memory copy. For tests."""
    global _memory
    with _lock:
        _memory = None
