"""Persisting conversations to Supabase.

Reached over PostgREST with the service-role key rather than over a direct
Postgres connection, so this needs no second connection pool beside the one
Phase 2 already runs, and no database password in the backend config.

The service-role key **bypasses Row Level Security**. Every function here
therefore filters by `user_id` itself, and takes that id from a verified token
rather than from anything the client sent. The RLS policies in
migrations/001_chat_history_rls.sql are the guarantee for the browser client,
which holds only the user's own token; they are not what protects these calls.

Nothing in here is allowed to break a conversation. A student mid-interview
should never lose their turn because a history write failed, so every function
reports failure by returning nothing and logging, and the caller carries on.
"""

from __future__ import annotations

import logging
from typing import Any, Final, Literal

import httpx

from .config import get_settings

logger = logging.getLogger(__name__)

Sender = Literal["user", "assistant", "system"]

TIMEOUT: Final = httpx.Timeout(10.0)
# A title is a label in a sidebar, not a document.
TITLE_CHARS: Final = 80


class HistoryUnavailable(RuntimeError):
    """Supabase could not be reached or refused the request."""


def _rest(path: str) -> str:
    return f"{get_settings().supabase_url.rstrip('/')}/rest/v1/{path}"


def _headers(*, prefer: str | None = None) -> dict[str, str]:
    settings = get_settings()
    headers = {
        "apikey": settings.supabase_service_role_key,
        "Authorization": f"Bearer {settings.supabase_service_role_key}",
        "Content-Type": "application/json",
    }
    if prefer:
        headers["Prefer"] = prefer
    return headers


async def _request(method: str, path: str, **kwargs: Any) -> Any:
    settings = get_settings()
    if not settings.history_configured:
        raise HistoryUnavailable("Supabase is not configured")

    headers = _headers()
    if "headers" in kwargs:
        headers.update(kwargs.pop("headers"))

    async with httpx.AsyncClient(timeout=TIMEOUT) as client:
        response = await client.request(method, _rest(path), headers=headers, **kwargs)

    if response.status_code >= 400:
        raise HistoryUnavailable(
            f"{method} {path} returned {response.status_code}: {response.text[:200]}"
        )
    if not response.content:
        return None
    return response.json()


_GREETING_WORDS: Final = frozenset(
    {
        "hey", "heyy", "hi", "hii", "hiii", "hello", "helo", "hlo",
        "yo", "salam", "aoa", "greetings", "test", "testing",
        "morning", "evening", "afternoon", "sup",
    }
)

_GENERIC_TITLES: Final = frozenset(
    {
        "new conversation",
        "getting started",
        "getting started...",
        "study abroad consultation",
        "study consultation",
        "hello vera",
        "hi vera",
        "hey vera",
        "good morning",
        "good evening",
        "good afternoon",
        "how are you",
        "hey there",
        "hello there",
        "conversation",
    }
)

_INTENT_KEYWORDS: Final = frozenset(
    {
        "study", "abroad", "masters", "master", "ms", "msc", "bachelors",
        "bachelor", "bs", "bsc", "phd", "doctorate", "diploma", "gpa", "cgpa",
        "ielts", "toefl", "pte", "gre", "gmat", "scholarship", "scholarships",
        "university", "universities", "college", "tuition", "fee", "fees",
        "visa", "admission", "admissions", "course", "courses", "major", "field",
        "degree", "engineering", "cs", "business", "nursing", "medicine",
        "germany", "australia", "canada", "uk", "usa", "us", "ireland", "europe",
    }
)


def is_greeting_or_generic(text: str) -> bool:
    """True for greetings, self-introductions, or generic openers without topic intent."""
    cleaned = " ".join(text.strip().lower().split())
    if not cleaned:
        return True

    import re

    normalized = re.sub(r"[^\w\s]", "", cleaned).strip()
    if not normalized:
        return True

    if normalized in _GENERIC_TITLES:
        return True

    words = normalized.split()
    first_word = words[0] if words else ""
    first_two = " ".join(words[:2]) if len(words) >= 2 else first_word

    # Opening greetings ("hey ...", "hello ...", "hi ...")
    if first_word in _GREETING_WORDS:
        has_academic_intent = any(
            w in {"masters", "bachelors", "phd", "degree", "ielts", "gpa", "course", "scholarship"}
            for w in words
        )
        if not has_academic_intent:
            return True

    # Introductions ("this is ...", "my name is ...", "i am ...")
    if first_two in {"this is", "my name", "i am", "im"}:
        has_academic_intent = any(
            w in {"masters", "bachelors", "phd", "degree", "ielts", "gpa", "course", "scholarship"}
            for w in words
        )
        if not has_academic_intent:
            return True

    filler = {
        "good", "morning", "evening", "afternoon", "there", "vera", "sir",
        "madam", "how", "are", "you", "doing", "im", "i", "am", "from",
        "this", "is", "iss", "here", "my", "name",
    }
    if all(w in _GREETING_WORDS or w in filler for w in words):
        return True

    if not any(w in _INTENT_KEYWORDS for w in words):
        return True

    return False


def is_generic_title(title: str | None) -> bool:
    """True if a title is a raw message snippet, greeting, or generic placeholder."""
    if not title:
        return True
    raw = title.strip()
    # Any title that ends with ellipsis was a truncated raw message snippet
    if raw.endswith("...") or raw.endswith("…"):
        return True

    cleaned = " ".join(raw.lower().split()).rstrip(".")
    if cleaned in _GENERIC_TITLES:
        return True

    # Any title starting with a greeting or intro
    for prefix in ("hey ", "hello ", "hi ", "this is ", "my name is ", "i am "):
        if cleaned.startswith(prefix):
            return True

    return is_greeting_or_generic(cleaned)


def derive_title(first_message: str) -> str:
    """A thread's initial label, taken from the first thing the student said.

    If the first message is a greeting, self-introduction, or pleasantry without
    explicit academic intent, return 'New conversation'.
    """
    cleaned = " ".join(first_message.split())
    if not cleaned or is_greeting_or_generic(cleaned):
        return "New conversation"
    if len(cleaned) <= TITLE_CHARS:
        return cleaned
    trimmed = cleaned[:TITLE_CHARS].rsplit(" ", 1)[0]
    return f"{trimmed or cleaned[:TITLE_CHARS]}..."


async def create_thread(user_id: str, *, title: str) -> dict[str, Any] | None:
    """Start a conversation. Returns the row, or None if it could not be saved."""
    try:
        rows = await _request(
            "POST",
            "chat_threads",
            headers=_headers(prefer="return=representation"),
            json={"user_id": user_id, "title": title[:TITLE_CHARS]},
        )
    except HistoryUnavailable as exc:
        logger.warning("Could not create a thread for %s: %s", user_id, exc)
        return None
    return rows[0] if rows else None


async def update_thread_title(user_id: str, thread_id: str, title: str) -> bool:
    """Rename a conversation. Returns False if it could not be saved."""
    cleaned = " ".join(title.split())[:TITLE_CHARS]
    if not cleaned:
        return False
    try:
        await _request(
            "PATCH",
            "chat_threads",
            headers=_headers(),
            params={"id": f"eq.{thread_id}", "user_id": f"eq.{user_id}"},
            json={"title": cleaned},
        )
    except HistoryUnavailable as exc:
        logger.warning("Could not retitle thread %s: %s", thread_id, exc)
        return False
    return True


async def list_threads(user_id: str, *, limit: int = 50) -> list[dict[str, Any]]:
    """This user's conversations, most recently active first.

    Selects explicit columns rather than `*`: the sidebar needs a title and a
    timestamp, and there is no reason for listing conversations to read their
    contents.
    """
    try:
        rows = await _request(
            "GET",
            "chat_threads",
            headers=_headers(),
            params={
                "select": "id,title,created_at,updated_at",
                "user_id": f"eq.{user_id}",
                "order": "updated_at.desc",
                "limit": str(limit),
            },
        )
    except HistoryUnavailable as exc:
        logger.warning("Could not list threads for %s: %s", user_id, exc)
        return []
    return rows or []


async def owns_thread(user_id: str, thread_id: str) -> bool:
    """Whether this thread belongs to this user.

    Checked explicitly because the service-role key bypasses RLS: without this,
    a valid token plus somebody else's thread id would be enough to read or
    append to their conversation.
    """
    try:
        rows = await _request(
            "GET",
            "chat_threads",
            headers=_headers(),
            params={
                "select": "id",
                "id": f"eq.{thread_id}",
                "user_id": f"eq.{user_id}",
                "limit": "1",
            },
        )
    except HistoryUnavailable as exc:
        logger.warning("Could not verify thread ownership: %s", exc)
        return False
    return bool(rows)


async def delete_thread(user_id: str, thread_id: str) -> bool:
    try:
        await _request(
            "DELETE",
            "chat_threads",
            headers=_headers(),
            params={"id": f"eq.{thread_id}", "user_id": f"eq.{user_id}"},
        )
    except HistoryUnavailable as exc:
        logger.warning("Could not delete thread %s: %s", thread_id, exc)
        return False
    return True


# --------------------------------------------------------------------------- #
# Messages
# --------------------------------------------------------------------------- #


async def append_message(
    user_id: str,
    thread_id: str,
    *,
    sender: Sender,
    content: str,
    kind: str | None = None,
    payload: dict[str, Any] | None = None,
) -> bool:
    """Add one message to a thread. Never raises.

    `payload` carries a rendered artifact - a diagnostic card, a list of course
    matches - stored exactly as it was sent so that reopening the conversation
    replays it rather than reconstructing it. `content` always holds readable
    text as well, so anything that only knows about `content` still works.

    Returns whether it was stored, so a caller that cares can say so - but no
    caller is expected to abandon a turn over it.
    """
    if not content.strip():
        return False
    row: dict[str, Any] = {
        "thread_id": thread_id,
        "user_id": user_id,
        "sender": sender,
        "content": content,
    }
    if kind:
        row["kind"] = kind
        row["payload"] = payload
    try:
        await _request(
            "POST",
            "chat_messages",
            headers=_headers(prefer="return=minimal"),
            json=row,
        )
    except HistoryUnavailable as exc:
        logger.warning("Could not save a %s message: %s", sender, exc)
        return False
    return True


async def list_messages(
    user_id: str, thread_id: str, *, limit: int = 500
) -> list[dict[str, Any]]:
    """One conversation, oldest first. Empty if it is not this user's."""
    if not await owns_thread(user_id, thread_id):
        return []
    params = {
        "thread_id": f"eq.{thread_id}",
        "user_id": f"eq.{user_id}",
        "order": "created_at.asc",
        "limit": str(limit),
    }
    try:
        rows = await _request(
            "GET",
            "chat_messages",
            headers=_headers(),
            params={**params, "select": "id,sender,content,kind,payload,created_at"},
        )
    except HistoryUnavailable as exc:
        # Most likely migration 002 has not been run, so `kind` and `payload`
        # do not exist yet. Falling back to the original columns keeps history
        # readable instead of failing the whole view over a missing feature.
        logger.warning("Reading thread %s without payloads: %s", thread_id, exc)
        try:
            rows = await _request(
                "GET",
                "chat_messages",
                headers=_headers(),
                params={**params, "select": "id,sender,content,created_at"},
            )
        except HistoryUnavailable as inner:
            logger.warning("Could not read thread %s: %s", thread_id, inner)
            return []
    return rows or []
