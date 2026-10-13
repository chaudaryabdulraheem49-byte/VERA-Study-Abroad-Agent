"""Text embeddings for syllabus vectors, with retry on provider rate limits.

Routed through the same provider abstraction as Phase 1, so the embedding
endpoint follows `LLM_PROVIDER` rather than being hard-wired to OpenAI.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Final

from ...config import get_settings
from ...llm_service import get_client, is_rate_limited

logger = logging.getLogger(__name__)

# A rate limit is worth waiting out; anything else fails fast.
_MAX_ATTEMPTS: Final = 4
_BASE_BACKOFF_SECONDS: Final = 2.0
# The provider caps how many inputs one embeddings call may carry.
_BATCH_SIZE: Final = 64


class EmbeddingError(RuntimeError):
    """Raised when text could not be embedded."""


async def embed_texts(texts: list[str]) -> list[list[float]]:
    """Embed a batch of texts, preserving input order.

    Batches are chunked and retried with exponential backoff on 429s, which is
    the failure mode that actually bites during a bulk ingest.
    """
    if not texts:
        return []

    settings = get_settings()
    client = get_client()
    if client is None:
        raise EmbeddingError(
            "No LLM provider configured - set GEMINI_API_KEY or OPENAI_API_KEY "
            "before ingesting course data."
        )

    vectors: list[list[float]] = []
    for start in range(0, len(texts), _BATCH_SIZE):
        batch = texts[start : start + _BATCH_SIZE]
        vectors.extend(
            await _embed_batch(
                client,
                settings.embedding_model,
                batch,
                dimensions=settings.embedding_dimensions,
            )
        )

    _assert_width(vectors, settings.embedding_dimensions)
    return vectors


async def embed_text(text: str) -> list[float]:
    """Embed one string - the query side of the hybrid search."""
    return (await embed_texts([text]))[0]


async def _embed_batch(
    client: object, model: str, batch: list[str], *, dimensions: int
) -> list[list[float]]:
    last_error: Exception | None = None
    # Both text-embedding-3-* and gemini-embedding-001 support an explicit
    # width; older models reject the argument, so it is dropped on a 400.
    send_dimensions = True

    for attempt in range(1, _MAX_ATTEMPTS + 1):
        try:
            extra = {"dimensions": dimensions} if send_dimensions else {}
            response = await client.embeddings.create(  # type: ignore[attr-defined]
                model=model, input=batch, **extra
            )
        except Exception as exc:  # noqa: BLE001 - provider SDKs raise broadly
            last_error = exc
            if send_dimensions and _rejects_dimensions(exc):
                logger.info(
                    "%s does not accept an explicit width; retrying without it",
                    model,
                )
                send_dimensions = False
                continue
            if not is_rate_limited(exc) or attempt == _MAX_ATTEMPTS:
                break
            delay = _BASE_BACKOFF_SECONDS * (2 ** (attempt - 1))
            logger.warning(
                "Embedding rate limited (attempt %d/%d); retrying in %.0fs",
                attempt,
                _MAX_ATTEMPTS,
                delay,
            )
            await asyncio.sleep(delay)
            continue

        # OpenAI returns an `index` per item and may reorder them, so it is
        # authoritative when present. Gemini's compatibility layer leaves the
        # first item's index null while numbering the rest, so a plain sort
        # would compare int against None - fall back to response order unless
        # every index is a real integer.
        items = list(response.data)
        if all(isinstance(item.index, int) for item in items):
            items.sort(key=lambda item: item.index)
        return [list(item.embedding) for item in items]

    raise EmbeddingError(
        f"Embedding failed after {_MAX_ATTEMPTS} attempts with model {model!r}: "
        f"{last_error}"
    ) from last_error


def _rejects_dimensions(exc: Exception) -> bool:
    """True when the provider refused the `dimensions` argument itself."""
    text = str(exc).lower()
    return "dimensions" in text and (
        "unexpected" in text or "unsupported" in text or "invalid" in text
    )


def _assert_width(vectors: list[list[float]], expected: int) -> None:
    """Catch a dimension mismatch here rather than as a Qdrant 400.

    A collection created at one width silently rejects every later vector of
    another, so the failure is far easier to read at the source.
    """
    for vector in vectors:
        if len(vector) != expected:
            raise EmbeddingError(
                f"Embedding width {len(vector)} does not match the configured "
                f"EMBEDDING_DIMENSIONS={expected}. The Qdrant collection is "
                "sized from that setting, so they must agree - recreate the "
                "collection after changing the embedding model."
            )
