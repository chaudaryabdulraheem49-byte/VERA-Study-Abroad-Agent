"""FastAPI application: the streaming chat endpoint that drives Phase 1.

`POST /api/chat/stream` accepts either JSON (`{session_id, message}`) or
multipart form data (the same fields plus a `file` transcript) and answers with
an SSE stream carrying:

    status             transient progress ("parsing your transcript")
    text_delta         assistant text, streamed
    slot_update        the current state of the onboarding fields
    transcript_parsed  structured OCR output for the upload
    diagnostic_card    the Phase 1 conversion card (JSON payload)
    university_matches the Phase 2 course matches the card unlocks
    error              a user-safe failure message
    done               terminal frame, carries the session id

`POST /api/chat/upload` parses a transcript on its own and answers with JSON
rather than a stream, for callers that want the extraction without a turn.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .auth import AuthenticatedUser, get_current_user
from . import chat_history
from .config import get_settings
from .course_matching import (
    MatchingUnavailable,
    MatchResult,
    build_guidance,
    build_query,
    expand_field,
    find_matches,
    _LEVEL_NAMES,
    target_degree_levels,
)
from .diagnostics import DiagnosticsUnavailable, build_card
from .gpa_converter import ConversionError, convert
from .llm_service import (
    _chunk_text,
    generate_title,
    TurnStatus,
    bare_country,
    country_aliases,
    extract_countries,
    extract_slots,
    is_affirmation,
    is_negation,
    asks_to_share_transcript,
    looks_like_noise,
    means_every_option,
    resolve_country_role,
    title_name,
    same_country,
    states_country_role,
    stream_reply,
)
from .ocr_service import TranscriptParseError, parse_transcript
from .scope import ScopeVerdict, classify, refusal_directive
from pydantic import BaseModel, ConfigDict

from .schemas import (
    AcademicScore,
    ChatRequest,
    DiagnosticCardPayload,
    EducationLevel,
    GradingScale,
    SessionState,
    SlotName,
    SlotPatch,
    SSEEvent,
    SSEEventType,
)
from .session_store import SessionStore, build_session_store

logger = logging.getLogger(__name__)

MAX_MESSAGE_CHARS: Final = 4000

SLOT_QUESTIONS: Final[dict[SlotName, str]] = {
    SlotName.FULL_NAME: "your full name as it appears on your passport",
    SlotName.NATIONALITY: "which country you hold citizenship in",
    SlotName.CGPA: "your CGPA or overall percentage, and the scale it is out of",
    SlotName.FIELD_OF_STUDY: "what you studied or are studying",
    SlotName.EDUCATION_LEVEL: (
        "what level that qualification is - intermediate, a Bachelor's, a "
        "Master's or a PhD"
    ),
    SlotName.TARGET_COUNTRY: "where you would like to study — Germany, Canada, Australia, the UK",
    SlotName.LANGUAGE_SCORE: "your IELTS or TOEFL score, or when you plan to take it",
}

SLOT_LABELS: Final[dict[SlotName, str]] = {
    SlotName.FULL_NAME: "name",
    SlotName.NATIONALITY: "nationality",
    SlotName.CGPA: "CGPA",
    SlotName.FIELD_OF_STUDY: "field of study",
    SlotName.EDUCATION_LEVEL: "level of study",
    SlotName.TARGET_COUNTRY: "target country",
    SlotName.LANGUAGE_SCORE: "language score",
}

# Appended to every planner directive. The directive is the last thing the
# model reads, and the system prompt alone was not enough: a lite model
# answered "where is South Africa" with a geography lesson regardless.
SCOPE_REMINDER: Final = (
    " Scope: answer study-abroad questions properly and in full - universities "
    "and where they are, admissions, entry requirements, grades, tests, "
    "transcripts, visas, funding, and student life in a destination all count. "
    "Decline only a topic with no connection to studying abroad, such as "
    "weather, sport, news, celebrities or general trivia: say in one short "
    "sentence that it is outside what you cover, then carry on with their "
    "application. When in doubt, treat the question as in scope and answer it."
)

# Appended whenever the student is asking about universities or programmes.
#
# The model was listing named universities with invented entry percentages -
# "Group of Eight typically require 65%+", "RMIT ... flexible entry" - directly
# above a grid of real, indexed courses. Two problems at once: the figures are
# not checked against anything, and they are a second, contradictory shortlist
# sitting on top of the one the search actually produced. The prose should set
# the student up for the grid, not compete with it.
# Leads the instruction rather than trailing it, and is stated as a limit on
# the reply's *shape* first, because a rule buried under three sentences of
# content guidance is the one a small model drops.
#
# The earlier wording also forbade stating any entry requirement at all, while
# the same directive handed the model system-computed notes that are entry
# requirements. Told both to use them and never to mention them, the model
# resolved the contradiction by ignoring the rule wholesale - and then invented
# institutions too. The prohibition is now on *unverified* specifics: facts
# supplied in the instruction are fine, anything from the model's own memory is
# not.
# The part that holds on every turn, shortlist or not. During onboarding the
# model was volunteering "an MSc in Advanced Computer Science" before it had
# run a single search - invented just as surely as a named university.
NO_INVENTED_SPECIFICS: Final = (
    " Never name a university, college, campus or specific named programme - "
    "not one, not as an example. You have no university database, so any "
    "institution or course you name is invented. Do not state any figure, "
    "requirement, fee or ranking that is not given to you verbatim above - do "
    "not convert, estimate or add to them."
)

SHORTLIST_DIRECTIVE: Final = (
    " HOW TO REPLY - this governs the whole answer and overrides anything "
    "above it. Write at most three short sentences of plain prose. Never write "
    "a list, numbered or bulleted."
    + NO_INVENTED_SPECIFICS
    + " A verified shortlist from a real course index is rendered on screen "
    "directly beneath your reply; naming your own would contradict it. The "
    "three sentences are: acknowledge what they asked for, say in general "
    "terms whether it is a realistic move and how their converted grade sits "
    "against it, then say the matching programmes are shown below. Stop there."
)

GREETING: Final = (
    "Hi, I am Vera, your study-abroad advisor. Tell me a little about yourself "
    "to get started — or drop your transcript straight into the chat and I will "
    "read it for you."
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    app.state.sessions = build_session_store()
    logger.info("Session store: %s", type(app.state.sessions).__name__)
    try:
        yield
    finally:
        await app.state.sessions.close()


app = FastAPI(
    title="Study Abroad Agent — Phase 1 Smart Diagnostics",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=list(get_settings().cors_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def get_store(request: Request) -> SessionStore:
    return request.app.state.sessions


# --------------------------------------------------------------------------- #
# Request parsing
# --------------------------------------------------------------------------- #


class Upload:
    """A validated in-memory upload."""

    __slots__ = ("content", "filename", "content_type")

    def __init__(self, content: bytes, filename: str, content_type: str | None) -> None:
        self.content = content
        self.filename = filename
        self.content_type = content_type


async def _read_request(
    request: Request, *, file_only: bool = False
) -> tuple[str | None, str, Upload | None]:
    """Return (session_id, message, upload) from a JSON or multipart request.

    `file_only` is for the upload endpoint, where a message is not expected and
    a missing file is the thing worth naming in the error.
    """
    content_type = (request.headers.get("content-type") or "").lower()

    if content_type.startswith("multipart/form-data"):
        form = await request.form()
        session_id = _as_str(form.get("session_id"))
        message = _as_str(form.get("message")) or ""
        upload: Upload | None = None

        candidate = form.get("file")
        if candidate is not None and hasattr(candidate, "read"):
            settings = get_settings()
            content = await candidate.read()  # type: ignore[union-attr]
            if len(content) > settings.max_upload_bytes:
                raise HTTPException(
                    status_code=413,
                    detail="That file is too large. Please upload a smaller scan.",
                )
            upload = Upload(
                content=content,
                filename=getattr(candidate, "filename", "transcript") or "transcript",
                content_type=getattr(candidate, "content_type", None),
            )
        if upload is None and (file_only or not message):
            raise HTTPException(
                status_code=422,
                detail=(
                    "Attach a transcript as `file`."
                    if file_only
                    else "Send a message, a file, or both."
                ),
            )
        return session_id, message[:MAX_MESSAGE_CHARS], upload

    try:
        payload = ChatRequest.model_validate(await request.json())
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail="Expected JSON with a non-empty `message`, or multipart form data.",
        ) from exc
    return payload.session_id, payload.message[:MAX_MESSAGE_CHARS], None


def _as_str(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #


@app.get("/api/health")
async def health() -> dict[str, Any]:
    settings = get_settings()
    return {
        "status": "ok",
        "llm_configured": settings.llm_enabled,
        "ocr_provider": settings.ocr_provider,
        "session_backend": type(app.state.sessions).__name__,
    }


@app.get("/api/session/{session_id}")
async def read_session(session_id: str, request: Request) -> dict[str, Any]:
    state = await get_store(request).get(session_id)
    if state is None:
        raise HTTPException(status_code=404, detail="Session not found or expired.")
    return _session_snapshot(state)


@app.delete("/api/session/{session_id}", status_code=status.HTTP_204_NO_CONTENT)
async def reset_session(session_id: str, request: Request) -> None:
    await get_store(request).delete(session_id)


@app.post("/api/chat/stream")
async def chat_stream(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> StreamingResponse:
    session_id, message, upload = await _read_request(request)
    store = get_store(request)
    state = await store.load_or_create(session_id)

    # The session keeps its own id either way; the thread is the *saved*
    # record, and only exists for a signed-in student with history configured.
    thread_id = await _ensure_thread(user, state, message)

    return StreamingResponse(
        _event_stream(state, message, upload, store, user=user, thread_id=thread_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # stop nginx from buffering the stream
            "X-Session-Id": state.session_id,
            **({"X-Thread-Id": thread_id} if thread_id else {}),
        },
    )


class ConvertRequest(BaseModel):
    """One grade, as a standalone conversion.

    The same `convert()` the chat uses - a second implementation would be a
    second set of numbers to keep in agreement, and these are numbers a
    student plans around.
    """

    model_config = ConfigDict(extra="forbid")

    raw_value: float
    scale: GradingScale = GradingScale.PERCENTAGE
    scale_max: float | None = None
    scale_min_pass: float | None = None
    # Only picks the minimum passing mark when the transcript does not state
    # one; Pakistan and India pass at 40%, China at 60%.
    country: str | None = None


@app.post("/api/convert")
async def convert_grade(payload: ConvertRequest) -> dict[str, Any]:
    """Grade conversion as a tool, independent of a conversation.

    Deliberately unauthenticated: it stores nothing, reads nothing, and
    answers from the request alone - an arithmetic endpoint, not a user one.
    """
    score = AcademicScore(
        raw_value=payload.raw_value,
        scale=payload.scale,
        scale_max=payload.scale_max,
        scale_min_pass=payload.scale_min_pass,
    )
    try:
        conversion = convert(score, country=payload.country)
    except ConversionError as exc:
        # 422, not 500: an unstated scale is the caller's to fix, and the
        # message says how.
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return conversion.model_dump(mode="json")


@app.get("/api/discovery")
async def discover_courses(
    country: str | None = None,
    degree_level: str | None = None,
    field_broad: str | None = None,
    query: str | None = None,
    max_tuition_usd: float | None = None,
    free_only: bool = False,
    post_study_work: bool = False,
    limit: int = 100,
) -> dict[str, Any]:
    """Browse the indexed catalogue by filter rather than by conversation.

    Reads Postgres only - no embedding call, so this works whether or not a
    course has a vector yet and costs nothing against the daily allowance.
    """
    import re

    from sqlalchemy import or_, select

    from .course_matching import _FIELD_EXPANSIONS, expand_field
    from .services.phase2.db import Course, session_scope

    query_stmt = select(Course)
    if country:
        query_stmt = query_stmt.where(Course.country.in_(country_aliases(country)))
    if degree_level:
        query_stmt = query_stmt.where(Course.degree_level == degree_level)

    search_raw = (field_broad or query or "").strip()
    if search_raw:
        expanded = expand_field(search_raw)
        is_known_abbrev = search_raw.lower() in _FIELD_EXPANSIONS

        search_conditions = []
        main_terms = set()
        if expanded and expanded.lower() != search_raw.lower():
            main_terms.add(expanded)
        if not is_known_abbrev:
            main_terms.add(search_raw)

        for term in main_terms:
            pattern = f"%{term}%"
            search_conditions.extend([
                Course.course_title.ilike(pattern),
                Course.field_broad.ilike(pattern),
                Course.field_narrow.ilike(pattern),
                Course.field_detailed.ilike(pattern),
                Course.syllabus_description.ilike(pattern),
            ])

        # For short acronyms (e.g. IT, AI, CS, MBA), match as a whole word boundary
        # in the course_title only (e.g. "Master of IT"), NEVER as a loose substring
        # '%it%' which would match 'university', 'credit', etc.
        if len(search_raw) <= 4 and re.match(r"^[A-Za-z0-9]+$", search_raw):
            safe_token = re.escape(search_raw)
            search_conditions.append(
                Course.course_title.op("~*")(rf"\y{safe_token}\y")
            )

        query_stmt = query_stmt.where(or_(*search_conditions))

    if free_only:
        query_stmt = query_stmt.where(Course.tuition_fee_usd <= 0)
    elif max_tuition_usd is not None:
        query_stmt = query_stmt.where(Course.tuition_fee_usd <= max_tuition_usd)
    if post_study_work:
        query_stmt = query_stmt.where(Course.post_study_work_eligible.is_(True))

    query_stmt = query_stmt.order_by(Course.tuition_fee_usd.asc()).limit(min(limit, 200))

    try:
        async with session_scope() as session:
            rows = (await session.execute(query_stmt)).scalars().all()
    except Exception as exc:  # noqa: BLE001 - the database may simply be down
        logger.warning("Discovery query failed: %s", exc)
        raise HTTPException(
            status_code=503, detail="The course index is unavailable."
        ) from exc

    return {
        "count": len(rows),
        "courses": [
            {
                "course_id": str(row.course_id),
                "course_title": row.course_title,
                "university_name": row.university_name,
                "country": row.country,
                "degree_level": row.degree_level,
                "field_broad": row.field_broad,
                "tuition_fee_usd": row.tuition_fee_usd,
                "tuition_fee_amount": row.tuition_fee_amount,
                "currency": row.currency,
                "min_gpa_percent": row.min_gpa_percent,
                "min_ielts_score": row.min_ielts_score,
                "duration_weeks": row.duration_weeks,
                "post_study_work_eligible": row.post_study_work_eligible,
                "deadline_type": row.deadline_type,
            }
            for row in rows
        ],
    }


@app.get("/api/history/threads")
async def list_threads(
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """The signed-in student's saved conversations, newest first."""
    if user.is_anonymous or not get_settings().history_configured:
        # An empty list rather than a 404: "you have no saved conversations"
        # and "this deployment does not save them" look the same to a sidebar,
        # and `enabled` tells the client which it is.
        return {"threads": [], "enabled": False}
    return {
        "threads": await chat_history.list_threads(user.id),
        "enabled": True,
    }


@app.get("/api/history/threads/{thread_id}")
async def read_thread(
    thread_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> dict[str, Any]:
    """One saved conversation. Empty unless it belongs to this user."""
    if user.is_anonymous or not get_settings().history_configured:
        raise HTTPException(status_code=404, detail="Chat history is not available.")

    messages = await chat_history.list_messages(user.id, thread_id)
    if not messages and not await chat_history.owns_thread(user.id, thread_id):
        # Deliberately the same answer as a thread that does not exist: saying
        # "that is not yours" confirms it exists and belongs to someone.
        raise HTTPException(status_code=404, detail="Conversation not found.")
    return {"thread_id": thread_id, "messages": messages}


@app.delete("/api/history/threads/{thread_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_thread(
    thread_id: str,
    user: AuthenticatedUser = Depends(get_current_user),
) -> None:
    if user.is_anonymous or not get_settings().history_configured:
        raise HTTPException(status_code=404, detail="Chat history is not available.")
    if not await chat_history.owns_thread(user.id, thread_id):
        raise HTTPException(status_code=404, detail="Conversation not found.")
    await chat_history.delete_thread(user.id, thread_id)


@app.post("/api/chat/upload")
async def chat_upload(
    request: Request,
    user: AuthenticatedUser = Depends(get_current_user),
) -> JSONResponse:
    """Parse a transcript on its own and return the extracted fields as JSON.

    The streaming endpoint also accepts a file, and that remains the path the
    chat UI uses because it answers in the same turn. This endpoint exists for
    callers that want the structured extraction without a conversation: it
    folds the values into the session exactly the same way, so a later chat
    turn picks up where this left off.
    """
    session_id, _, upload = await _read_request(request, file_only=True)
    assert upload is not None  # _read_request refuses the request without one

    store = get_store(request)
    state = await store.load_or_create(session_id)

    try:
        transcript = await parse_transcript(
            upload.content, upload.filename, upload.content_type
        )
    except TranscriptParseError as exc:
        # A bad scan is the student's problem to fix, not a server fault, and
        # the session is left untouched so they can simply try again.
        return JSONResponse(
            status_code=422,
            content={"detail": str(exc), "session_id": state.session_id},
        )

    state.transcript = transcript
    state.transcript_parsed = True
    state.slots.merge(
        SlotPatch(
            full_name=title_name(transcript.student_name)
            if transcript.student_name
            else None,
            field_of_study=transcript.field_of_study,
            education_level=transcript.education_level,
            cgpa=transcript.to_academic_score(),
        ),
        from_ocr=True,
    )
    state.append("system", f"Transcript uploaded and parsed ({upload.filename}).")
    await store.save(state)

    return JSONResponse(
        content={
            "session_id": state.session_id,
            "transcript_parsed": True,
            "extracted": transcript.model_dump(mode="json"),
            "slots": _slot_snapshot(state),
        },
        headers={"X-Session-Id": state.session_id},
    )


@app.exception_handler(TranscriptParseError)
async def _transcript_error_handler(
    request: Request, exc: TranscriptParseError
) -> JSONResponse:
    return JSONResponse(status_code=422, content={"detail": str(exc)})


# --------------------------------------------------------------------------- #
# The stream
# --------------------------------------------------------------------------- #


async def _event_stream(
    state: SessionState,
    message: str,
    upload: Upload | None,
    store: SessionStore,
    *,
    user: AuthenticatedUser | None = None,
    thread_id: str | None = None,
) -> AsyncIterator[str]:
    """Drive one turn: ingest, fill slots, stream a reply, maybe emit a card."""
    turn = TurnStatus()
    # Collected as the reply streams and written once at the end: a hundred
    # token-sized inserts per turn would cost more than the conversation.
    reply_chunks: list[str] = []
    try:
        # A brand-new session has only the client-side greeting behind it, and
        # that greeting invites the student to introduce themselves - so treat a
        # bare opening reply ("Usama khan") as answering the first questions.
        if not state.messages and not state.awaiting:
            state.awaiting = state.slots.missing()[:2]
        if message:
            state.append("user", message)

        # 1. Transcript first — an upload can satisfy three slots at once, and
        #    the reply we stream afterwards must already know about them.
        transcript_ingested = False
        if upload is not None:
            yield _frame(
                SSEEventType.STATUS,
                {"stage": "parsing", "message": f"Reading {upload.filename}..."},
            )
            previous = state.transcript
            async for chunk in _ingest_upload(state, upload):
                yield chunk
            transcript_ingested = state.transcript is not previous

        # 2. Topic guardrail. Runs before extraction on purpose: otherwise
        #    "what is the weather in Tokyo" would file Tokyo as a destination.
        verdict = classify(message, state) if message else ScopeVerdict.IN_SCOPE
        if verdict is not ScopeVerdict.IN_SCOPE:
            logger.info(
                "Refusing out-of-scope message in %s (%s)", state.session_id, verdict
            )
            directive, fallback = refusal_directive(verdict, state)
            reply_parts: list[str] = []
            async for token in stream_reply(
                state, directive, fallback=fallback, status=turn
            ):
                reply_parts.append(token)
                reply_chunks.append(token)
                yield _frame(SSEEventType.TOKEN, {"text": token})
            state.append("assistant", "".join(reply_parts))
            await _save_turn(user, thread_id, message, "".join(reply_chunks))
            yield _frame(
                SSEEventType.DONE,
                {
                    "session_id": state.session_id,
                    "diagnostics_unlocked": state.diagnostics_unlocked,
                },
            )
            return

        # 3. Free-text extraction (multi-field capable).
        slots_changed = transcript_ingested
        # Set when the student changes what they are asking for rather than
        # what we know about them: the report stays put, the shortlist moves.
        rematch = False
        deferred: list[SlotName] = []
        ambiguous_country: str | None = None
        if message:
            # Named so the client can show which step is running rather than a
            # single undifferentiated spinner. This is real work - a model call
            # - not a decorative delay.
            yield _frame(
                SSEEventType.STATUS,
                {"stage": "understanding", "message": "Reading what you said..."},
            )
            patch = await extract_slots(message, state, status=turn)

            # While transcript values are awaiting review, the review is the
            # only question on the table. Anything else the student mentions is
            # set aside rather than recorded, so the profile cannot grow around
            # figures they have not yet checked.
            if state.slots.pending_confirmation():
                patch, deferred = _restrict_to_confirmation(patch, state)
                # A country mentioned mid-review is remembered but not placed:
                # the review is the only question on the table, and the "which
                # slot" question is asked once it clears.
                if (
                    state.pending_country is None
                    and state.slots.nationality is None
                    and state.slots.target_country is None
                ):
                    state.pending_country = bare_country(message)

            # A country already awaiting a role owns this turn: until the
            # student says which slot it belongs to, no country may be filed.
            elif state.pending_country:
                if states_country_role(message) and (
                    patch.nationality or patch.target_country
                ):
                    # They restated it with phrasing that settles it, e.g.
                    # "I'm from Pakistan" - their own wording wins, and it may
                    # name a different country than the one we were holding.
                    state.pending_country = None
                elif (role := resolve_country_role(message)) is not None:
                    setattr(patch, role, state.pending_country)
                    state.pending_country = None
                else:
                    # "yes" answers an either/or question with nothing at all.
                    patch.nationality = None
                    patch.target_country = None

            # A grade that replaces one already on the profile. Held until the
            # student confirms, because every figure downstream - the
            # conversion, the eligibility filter, the shortlist - moves with
            # it, and a silent swap gives them no way to notice.
            if state.pending_grade is not None:
                if is_affirmation(message):
                    patch.cgpa = state.pending_grade
                    state.pending_grade = None
                elif is_negation(message):
                    state.pending_grade = None
                    patch.cgpa = None
                elif patch.cgpa is not None:
                    # Naming a grade instead of answering yes or no settles it
                    # just as well - that is the number they want.
                    state.pending_grade = None
                else:
                    patch.cgpa = None
            elif (
                patch.cgpa is not None
                and state.slots.cgpa is not None
                and patch.cgpa != state.slots.cgpa
                # An OCR value the student has not yet checked is not an answer
                # they gave, so replacing it needs no permission from them.
                and SlotName.CGPA in state.slots.user_confirmed
            ):
                state.pending_grade = patch.cgpa
                patch.cgpa = None

            # Several destinations in one message. Recording the first and
            # discarding the rest is the silent kind of wrong - the dropped
            # one is never mentioned again - so they are held until the
            # student says whether they meant all of them.
            if state.pending_multi_country:
                # "Both" is the commonest answer here and is not a plain yes,
                # so it used to settle nothing - and the destinations the
                # student had just agreed to were dropped in silence.
                if is_affirmation(message) or means_every_option(message):
                    chosen = state.pending_multi_country
                    patch.target_country = chosen[0]
                    patch.extra_countries = chosen[1:]
                    state.pending_multi_country = []
                elif is_negation(message):
                    state.pending_multi_country = []
                    patch.target_country = None
                elif named := extract_countries(message):
                    # Naming a country instead of answering yes or no settles
                    # it just as well.
                    patch.target_country = named[0]
                    patch.extra_countries = named[1:]
                    state.pending_multi_country = []
            elif (
                not state.slots.target_country
                and len(destinations := _destinations_named(message, state, patch)) > 1
            ):
                state.pending_multi_country = destinations
                patch.target_country = None
                patch.extra_countries = []

            # A lone country name is ambiguous while both country slots are
            # open: "Germany" could be citizenship or destination. Guessing
            # produces a confident, wrong profile, so ask instead.
            if (
                not state.pending_multi_country
                and (candidate := bare_country(message)) is not None
                and _country_is_ambiguous(candidate, state)
            ):
                state.pending_country = candidate
                patch.nationality = None
                patch.target_country = None

            # Destination equal to citizenship: check before recording.
            known_nationality = patch.nationality or state.slots.nationality
            if state.pending_same_country:
                if patch.target_country and not same_country(
                    patch.target_country, state.pending_same_country
                ):
                    # They named somewhere else - that answers it.
                    state.pending_same_country = None
                elif is_affirmation(message):
                    patch.target_country = state.pending_same_country
                    state.pending_same_country = None
                elif is_negation(message):
                    state.pending_same_country = None
                    patch.target_country = None
                else:
                    patch.target_country = None
            elif patch.target_country and same_country(
                patch.target_country, known_nationality
            ):
                state.pending_same_country = patch.target_country
                patch.target_country = None

            if state.pending_country:
                ambiguous_country = state.pending_country
                deferred = [
                    n
                    for n in deferred
                    if n not in (SlotName.NATIONALITY, SlotName.TARGET_COUNTRY)
                ]

            if patch.confirms_ocr:
                state.slots.confirm_all_ocr()
            # A stated preference is not a slot - it does not gate the
            # barrier - but it does steer the search, and it persists so a
            # later turn still knows what they asked for.
            if (
                patch.desired_level is not None
                and patch.desired_level != state.desired_level
            ):
                state.desired_level = patch.desired_level
                rematch = True
            changed = state.slots.merge(patch)
            if changed or patch.confirms_ocr:
                slots_changed = True
                # A changed destination or subject should also refresh the
                # shortlist, even when the report itself reads the same.
                if state.diagnostics_unlocked:
                    rematch = True
                yield _frame(SSEEventType.SLOT_UPDATE, _slot_snapshot(state))

        # 4. Decide what this turn should say.
        directive, fallback, card = _plan_turn(
            state,
            had_upload=transcript_ingested,
            slots_changed=slots_changed,
            # Nothing was understood and the text does not read as words: say so
            # rather than treating keyboard mashing as an answer.
            noise=bool(message) and not slots_changed and looks_like_noise(message),
            deferred=deferred,
            ambiguous_country=ambiguous_country,
            multi_country=state.pending_multi_country or None,
            same_country_as_home=state.pending_same_country,
            grade_change=state.pending_grade,
            # Said they want their transcript read but sent nothing yet. Only
            # when no file arrived - once one has, it is parsed, not awaited.
            awaiting_transcript=(
                bool(message)
                and not transcript_ingested
                and asks_to_share_transcript(message)
            ),
        )

        if card is not None:
            yield _frame(
                SSEEventType.STATUS,
                {"stage": "diagnosing", "message": "Working out where you stand..."},
            )

        # 5. Say where they stand.
        #
        # On the turn that produces the report, the text is written here rather
        # than by the model. Four separate instructions told it not to list
        # universities - leading the prompt, naming the failure, forbidding
        # examples - and it listed Waterloo, UBC and Concordia with invented
        # entry requirements anyway, directly above the real indexed shortlist.
        #
        # There is nothing left to tighten: a lite model will not reliably obey
        # a prohibition, and the cost of it disobeying is a student acting on
        # admissions figures nobody checked. The deterministic sentences below
        # quote the computed conversion and nothing else, and the card and the
        # verified grid follow immediately - which is where the real content
        # was always meant to live.
        reply_parts: list[str] = []
        if card is not None:
            # Chunked rather than sent whole: the text is deterministic, but
            # the student should still see it arrive. One frame would make the
            # report turn - the one that matters most - the only turn in the
            # conversation that lands as a block.
            for chunk in _chunk_text(fallback):
                reply_parts.append(chunk)
                reply_chunks.append(chunk)
                yield _frame(SSEEventType.TOKEN, {"text": chunk})
                # Yield to the event loop so each frame is flushed on its own
                # rather than the whole set landing in one write.
                await asyncio.sleep(0)
        else:
            async for token in stream_reply(
                state, directive + SCOPE_REMINDER, fallback=fallback, status=turn
            ):
                reply_parts.append(token)
                reply_chunks.append(token)
                yield _frame(SSEEventType.TOKEN, {"text": token})
        state.append("assistant", "".join(reply_parts))

        # 6. Emit the diagnostic card once the barrier is cleared, then the
        #    course matches it unlocks. The card goes out first so the student
        #    sees their standing while the search runs.
        if card is not None:
            state.diagnostics_unlocked = True
            state.last_card = card
            payload = card.model_dump(mode="json")
            yield _frame(SSEEventType.DIAGNOSTIC_CARD, payload)

            # The profile is complete here, so the sidebar label can finally
            # say what the conversation is about rather than quoting whatever
            # the student happened to type first. Backgrounded: a rename must
            # not hold up the card or the shortlist behind it.
            retitle = asyncio.create_task(
                _retitle_from_profile(user, thread_id, state)
            )
            _background_tasks.add(retitle)
            retitle.add_done_callback(_background_tasks.discard)
            # Saved exactly as sent, so reopening the conversation replays the
            # report rather than rebuilding it from the transcript.
            await _save_artifact(
                user,
                thread_id,
                kind="diagnostic_card",
                summary="Diagnostic report",
                payload=payload,
            )

            yield _frame(
                SSEEventType.STATUS,
                {"stage": "matching", "message": "Finding programmes that fit..."},
            )
            async for frame in _emit_matches(
                state, card, user=user, thread_id=thread_id
            ):
                yield frame

        elif rematch and state.last_card is not None:
            # The report is unchanged and must not be re-sent, but what the
            # student is asking for has changed - a different level, a
            # different destination, a different subject. Matching runs again
            # on its own so the grid answers the question actually asked.
            yield _frame(
                SSEEventType.STATUS,
                {"stage": "matching", "message": "Finding programmes that fit..."},
            )
            async for frame in _emit_matches(
                state, state.last_card, user=user, thread_id=thread_id
            ):
                yield frame

        if turn.rate_limited:
            yield _frame(
                SSEEventType.ERROR,
                {
                    "message": (
                        "I am being rate limited by the AI provider right now, so "
                        "that reply came from my basic script. Your details are "
                        "still saved - wait about a minute and I will be back to "
                        "full strength."
                    ),
                    "recoverable": True,
                },
            )

        await _save_turn(user, thread_id, message, "".join(reply_chunks))
        retitle_task = asyncio.create_task(
            _maybe_retitle_thread(user, thread_id, state, message)
        )
        _background_tasks.add(retitle_task)
        retitle_task.add_done_callback(_background_tasks.discard)

        yield _frame(
            SSEEventType.DONE,
            {
                "session_id": state.session_id,
                "diagnostics_unlocked": state.diagnostics_unlocked,
            },
        )
    except asyncio.CancelledError:
        # The browser navigated away mid-stream: keep whatever we learned.
        await store.save(state)
        raise
    except Exception:
        logger.exception("Unhandled failure in chat stream %s", state.session_id)
        yield _frame(
            SSEEventType.ERROR,
            {
                "message": "Something went wrong on my side. Please send that again.",
                "session_id": state.session_id,
            },
        )
        yield _frame(SSEEventType.DONE, {"session_id": state.session_id})
    finally:
        await store.save(state)


async def _ingest_upload(state: SessionState, upload: Upload) -> AsyncIterator[str]:
    """Parse a transcript and fold what it yields into the slot state."""
    try:
        transcript = await parse_transcript(
            upload.content, upload.filename, upload.content_type
        )
    except TranscriptParseError as exc:
        state.append("system", f"Transcript parsing failed: {exc}")
        yield _frame(
            SSEEventType.ERROR, {"message": str(exc), "recoverable": True}
        )
        return

    state.transcript = transcript
    state.transcript_parsed = True
    patch = SlotPatch(
        # Transcripts print names in caps as a typesetting convention, not
        # because the name is capitalised - normalise so an uploaded name and
        # a typed one look the same in the profile.
        full_name=title_name(transcript.student_name) if transcript.student_name else None,
        field_of_study=transcript.field_of_study,
        education_level=transcript.education_level,
        cgpa=transcript.to_academic_score(),
    )
    changed = state.slots.merge(patch, from_ocr=True)

    state.append(
        "system",
        "Transcript parsed. "
        + ", ".join(
            filter(
                None,
                [
                    f"name={transcript.student_name}" if transcript.student_name else None,
                    f"institution={transcript.institution_name}"
                    if transcript.institution_name
                    else None,
                    f"cgpa={transcript.cumulative_gpa or transcript.percentage}"
                    if (transcript.cumulative_gpa or transcript.percentage)
                    else None,
                    f"field={transcript.field_of_study}"
                    if transcript.field_of_study
                    else None,
                    f"backlogs={transcript.backlogs}" if transcript.backlogs else None,
                ],
            )
        ),
    )

    yield _frame(SSEEventType.TRANSCRIPT_PARSED, transcript.model_dump(mode="json"))
    if changed:
        yield _frame(SSEEventType.SLOT_UPDATE, _slot_snapshot(state))


def _destinations_named(
    message: str, state: SessionState, patch: SlotPatch | None = None
) -> list[str]:
    """Countries that are plainly destinations this turn.

    Two sources, because the student and the model phrase it differently.

    The model is checked first and trusted outright: when it files
    `target_country` as "Australia and UK" it has already decided both are
    destinations, and no turn-context test is needed. That string is also what
    made this necessary - stored verbatim it becomes a country nothing in the
    index is in, so the filter quietly matches nothing.

    Falling back to the raw message needs more care. "I am from India and want
    to study in Australia" names two countries and one destination, so a bare
    count is not enough: it only reports more than one when the turn is about
    where they want to go, and citizenship is removed first.

    The two sources are also merged rather than tried in turn, because they
    fail on different inputs. The literal matcher cannot read "Austraalia UK"
    as two countries - it only sees the UK - while the model reads the typo
    and files Australia. Taking whichever source fires first would then record
    one destination silently when the student plainly named two.
    """
    # Citizenship is not a destination, and it may be arriving in this very
    # patch rather than already being on the profile.
    home = (patch.nationality if patch is not None else None) or state.slots.nationality

    from_model: list[str] = []
    if patch is not None and patch.target_country:
        from_model = extract_countries(patch.target_country)

    named = extract_countries(message)

    if from_model:
        # The model filing a destination settles what this turn is about, so
        # the turn-context test below is not needed: anything else it names is
        # a second destination, not a possible citizenship.
        return _dedupe_countries([*from_model, *named], home)

    if len(named) < 2:
        return []

    asked_for_destination = SlotName.TARGET_COUNTRY in state.awaiting
    if not asked_for_destination and not state.slots.nationality:
        # Citizenship is still open, so one of these may well be it.
        return []

    return _dedupe_countries(named, home)


def _dedupe_countries(countries: list[str], home: str | None) -> list[str]:
    """Distinct destinations, in the order named, minus the student's own country.

    Compared with `same_country` rather than by string, so "UK" and "United
    Kingdom" are not reported as two places to apply to.
    """
    out: list[str] = []
    for country in countries:
        if home and same_country(country, home):
            continue
        if any(same_country(country, seen) for seen in out):
            continue
        out.append(country)
    return out if len(out) > 1 else []


def _country_is_ambiguous(country: str, state: SessionState) -> bool:
    """True when a lone country name could reasonably belong to more than one slot.

    With both slots open it could be either. With one already filled by a
    *different* country it could be the open slot or a change of mind about the
    filled one - and silently overwriting an answer the student already gave is
    the failure this prevents. Repeating a country already recorded is not
    ambiguous; that is handled elsewhere.
    """
    if same_country(country, state.slots.nationality) or same_country(
        country, state.slots.target_country
    ):
        return False

    # If the previous turn asked for exactly one of the two country slots, a
    # bare country is simply the answer to that question. Querying it there
    # would mean asking "citizenship or destination?" immediately after asking
    # "where would you like to study?".
    awaited = [
        slot
        for slot in state.awaiting
        if slot in (SlotName.NATIONALITY, SlotName.TARGET_COUNTRY)
    ]
    return len(awaited) != 1


def _describe_score(score: AcademicScore | None) -> str:
    """A grade as a student would say it: "3.2 out of 4.0", "82%"."""
    if score is None:
        return "your previous grade"

    def trim(value: float) -> str:
        # 3.0 reads as "3", 3.2 as "3.2" - trailing zeros look like precision
        # the student did not give.
        return f"{value:g}"

    if score.scale is GradingScale.PERCENTAGE:
        return f"{trim(score.raw_value)}%"
    if score.scale_max:
        return f"{trim(score.raw_value)} out of {trim(score.scale_max)}"
    return trim(score.raw_value)


def _list_countries(countries: list[str]) -> str:
    """"Australia and the UK", "Australia, the UK and Canada"."""
    named = [_with_article(c) for c in countries]
    if not named:
        # Previously an IndexError. Every existing caller happens to check
        # first, so an empty list never reached it - which made it a trap for
        # the next one rather than a safe helper.
        return ""
    if len(named) == 1:
        return named[0]
    return ", ".join(named[:-1]) + " and " + named[-1]


def _with_article(country: str) -> str:
    """Countries whose names take "the" read wrong without it."""
    return f"the {country}" if country in {"UK", "USA", "UAE", "Netherlands"} else country


def _country_question(country: str, state: SessionState) -> str:
    """Phrase the disambiguation around what is already known."""
    nationality = state.slots.nationality
    target = state.slots.target_country

    if nationality and target:
        return (
            f"you already have {nationality} as citizenship and {target} as the "
            f"destination, so ask which of the two they want to change to {country}"
        )
    if nationality:
        return (
            f"they already gave {nationality} as their citizenship, so ask "
            f"whether {country} is where they want to study, or whether they "
            f"are changing their citizenship to {country}"
        )
    if target:
        return (
            f"they already gave {target} as their destination, so ask whether "
            f"{country} is their citizenship, or whether they are changing "
            f"their destination to {country}"
        )
    return (
        f"ask whether {country} is where they hold citizenship or where they "
        "would like to study"
    )


def _country_question_fallback(country: str, state: SessionState) -> str:
    """The same question, phrased for the deterministic fallback path."""
    nationality = state.slots.nationality
    target = state.slots.target_country

    if nationality and target:
        return (
            f"I have {nationality} as your citizenship and {target} as where you "
            f"want to study. Which of those did you mean to change to {country}?"
        )
    if nationality:
        return (
            f"You told me you hold {nationality} citizenship. Is {country} where "
            f"you want to study, or are you changing your citizenship to {country}?"
        )
    if target:
        return (
            f"You told me you want to study in {target}. Is {country} where you "
            f"hold citizenship, or are you changing your destination to {country}?"
        )
    return (
        f"Just so I record it correctly — is {country} where you hold "
        "citizenship, or where you would like to study?"
    )


async def _ensure_thread(
    user: AuthenticatedUser, state: SessionState, message: str
) -> str | None:
    """The saved thread for this session, creating one on the first message.

    Returns None whenever history is not available - not signed in, Supabase
    not configured, or the write failed. The conversation then behaves exactly
    as it did before accounts existed, which is the point: persistence is an
    addition, never a precondition.
    """
    if user.is_anonymous or not get_settings().history_configured:
        return None
    if state.thread_id:
        return state.thread_id

    # Created with a label taken from the first message (or 'New conversation' if a greeting).
    # If the first message has real intent and substance, we kick off generation immediately.
    # If it is a greeting ('hey', 'hello'), title generation is deferred until future turns
    # provide sufficient context.
    initial_title = chat_history.derive_title(message)
    thread = await chat_history.create_thread(user.id, title=initial_title)
    if thread is None:
        return None
    state.thread_id = str(thread["id"])
    state.saved_title = initial_title

    if not chat_history.is_greeting_or_generic(message):
        task = asyncio.create_task(
            _retitle_thread(user.id, state.thread_id, message, state=state)
        )
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)

    return state.thread_id


# asyncio keeps only a weak reference to a running task, so one that nothing
# holds can be collected before it finishes.
_background_tasks: set[asyncio.Task[Any]] = set()


def _title_case_subject(field: str) -> str:
    """"graphic design" -> "Graphic Design", without flattening acronyms.

    `str.title()` turns "IT" into "It" and "MBA" into "Mba", which looks like
    a typo in a sidebar.
    """
    words = []
    for word in field.split():
        if word.isupper() and len(word) <= 4:
            words.append(word)  # IT, MBA, AI, HR
        else:
            words.append(word[:1].upper() + word[1:])
    return " ".join(words)


def profile_title(state: SessionState) -> str | None:
    """A label built from what the student actually told us.

    Assembled rather than generated: uses structured values the student gave,
    such as degree level applied for, field of study, and target country
    (e.g., 'Masters in CS - Australia' or 'Masters in Computer Science').
    Returns None when there is not enough context to beat the existing label.
    """
    slots = state.slots

    # The level they are applying FOR, not the one they hold.
    if state.desired_level is not None:
        level = _LEVEL_NAMES.get(state.desired_level)
    else:
        wanted = target_degree_levels(slots.education_level)
        level = wanted[0] if wanted else None

    field = _title_case_subject(slots.field_of_study) if slots.field_of_study else None
    where = _list_countries(slots.destinations())

    # A title that says only "Masters" or only "Australia" tells a student
    # nothing when every conversation says the same - so at least two parts.
    parts = [p for p in (level, field) if p]
    if not parts or (len(parts) == 1 and not where):
        return None

    title = " ".join(parts)
    if where:
        title = f"{title} - {where}"
    return title[:chat_history.TITLE_CHARS]


async def _retitle_from_profile(
    user: AuthenticatedUser | None, thread_id: str | None, state: SessionState
) -> None:
    """Upgrade the label once the profile is complete. Never raises."""
    if user is None or thread_id is None:
        return
    title = profile_title(state)
    if not title or title == state.saved_title:
        return
    if await chat_history.update_thread_title(user.id, thread_id, title):
        # Remembered so a later turn does not rewrite the same value.
        state.saved_title = title


def extract_title_context(
    state: SessionState, current_message: str | None = None
) -> str:
    """Build a rich conversation context to help the LLM generate a focused title."""
    parts: list[str] = []

    profile_clues: list[str] = []
    if state.desired_level is not None:
        lvl = _LEVEL_NAMES.get(state.desired_level)
        if lvl:
            profile_clues.append(f"Level: {lvl}")
    if state.slots.field_of_study:
        profile_clues.append(f"Field: {state.slots.field_of_study}")
    dests = state.slots.destinations()
    if dests:
        profile_clues.append(f"Country: {', '.join(dests)}")
    if state.slots.cgpa:
        profile_clues.append(f"GPA: {state.slots.cgpa.raw_value}")
    if profile_clues:
        parts.append(f"Profile: {'; '.join(profile_clues)}")

    user_msgs: list[str] = []
    for m in state.messages:
        if m.role == "user" and m.content.strip():
            user_msgs.append(m.content.strip())
    if current_message and current_message.strip():
        if not user_msgs or user_msgs[-1] != current_message.strip():
            user_msgs.append(current_message.strip())

    substantive = [m for m in user_msgs if not chat_history.is_greeting_or_generic(m)]
    messages_to_use = substantive if substantive else user_msgs

    for msg in messages_to_use[-4:]:
        parts.append(f"Student: {msg}")

    return "\n".join(parts)


async def _retitle_thread(
    user_id: str,
    thread_id: str,
    message_or_context: str,
    state: SessionState | None = None,
) -> None:
    """Replace a generic or first-message label with a generated one. Never raises."""
    if not message_or_context or chat_history.is_greeting_or_generic(message_or_context):
        return
    try:
        title = await generate_title(message_or_context)
        if title and not chat_history.is_generic_title(title):
            if await chat_history.update_thread_title(user_id, thread_id, title):
                if state is not None:
                    state.saved_title = title
    except Exception as exc:  # noqa: BLE001 - a background task must not escape
        logger.info("Could not retitle thread %s: %s", thread_id, exc)


async def _maybe_retitle_thread(
    user: AuthenticatedUser | None,
    thread_id: str | None,
    state: SessionState,
    current_message: str | None = None,
) -> None:
    """Evaluate whether this thread needs its title created or upgraded after a turn. Never raises."""
    if user is None or user.is_anonymous or thread_id is None:
        return

    # 1. Deterministic profile-based topic title (highest priority)
    p_title = profile_title(state)
    if p_title and p_title != state.saved_title:
        if await chat_history.update_thread_title(user.id, thread_id, p_title):
            state.saved_title = p_title
            return

    # 2. Check if we should generate an intent-based title with the LLM.
    # Re-trigger when:
    # - The saved title is generic ('New conversation', greeting, or empty) and substantive context exists
    # - Or we are in early turns (turns 2-4) and the saved title is still just the raw first message slice
    current_saved = state.saved_title
    is_saved_generic = chat_history.is_generic_title(current_saved)

    user_msgs = [m.content.strip() for m in state.messages if m.role == "user" and m.content.strip()]
    turn_count = len(user_msgs)

    should_generate = False
    if is_saved_generic:
        context = extract_title_context(state, current_message)
        if context and not chat_history.is_greeting_or_generic(context):
            should_generate = True
    elif turn_count in (2, 3, 4) and current_saved and not p_title:
        first_raw = user_msgs[0] if user_msgs else ""
        if current_saved == chat_history.derive_title(first_raw):
            context = extract_title_context(state, current_message)
            if context and len(user_msgs) >= 2:
                should_generate = True

    if should_generate:
        context = extract_title_context(state, current_message)
        if context and not chat_history.is_greeting_or_generic(context):
            task = asyncio.create_task(
                _retitle_thread(user.id, thread_id, context, state=state)
            )
            _background_tasks.add(task)
            task.add_done_callback(_background_tasks.discard)


async def _save_artifact(
    user: AuthenticatedUser | None,
    thread_id: str | None,
    *,
    kind: str,
    summary: str,
    payload: dict[str, Any],
) -> None:
    """Store a rendered artifact in the transcript. Never raises.

    `summary` is the readable `content` every row carries, so a reader that
    knows nothing about payloads still sees something sensible where the card
    appeared.
    """
    if user is None or thread_id is None:
        return
    await chat_history.append_message(
        user.id,
        thread_id,
        sender="system",
        content=summary,
        kind=kind,
        payload=payload,
    )


async def _save_turn(
    user: AuthenticatedUser | None,
    thread_id: str | None,
    message: str,
    reply: str,
) -> None:
    """Write one exchange. Failures are logged, never raised.

    Called after the reply has finished streaming rather than per token: a
    hundred inserts per turn would cost more than the conversation, and a
    half-written reply is not worth saving anyway.
    """
    if user is None or thread_id is None:
        return
    if message.strip():
        await chat_history.append_message(
            user.id, thread_id, sender="user", content=message
        )
    if reply.strip():
        await chat_history.append_message(
            user.id, thread_id, sender="assistant", content=reply
        )


async def _emit_matches(
    state: SessionState,
    card: DiagnosticCardPayload,
    *,
    user: AuthenticatedUser | None = None,
    thread_id: str | None = None,
) -> AsyncIterator[str]:
    """Search the course index and emit the matches, or say why there are none.

    A failure here must never break the stream: the diagnostic report is
    already delivered and useful on its own, so the course index being down
    is a degraded turn, not a failed one.
    """
    try:
        result = await find_matches(state, card)
    except MatchingUnavailable as exc:
        logger.warning("Course matching unavailable for %s: %s", state.session_id, exc)
        if exc.quota_exhausted:
            message = (
                "Your diagnostic report is ready. Programme matching is paused "
                "until tomorrow - the daily search allowance for this service "
                "has been used up. It resets automatically; everything else on "
                "this page still stands."
            )
        else:
            message = (
                "Your diagnostic report is ready, but I could not reach the "
                "course index just now, so there are no programme matches "
                "below. Everything else on this page still stands."
            )
        yield _frame(
            SSEEventType.ERROR, {"message": message, "recoverable": True}
        )
        return

    # An empty result is information, not a fault: it rides on the same event
    # as a full one, with a note saying which part of the profile nothing in
    # the index satisfies, so the student knows what to change.
    state.last_matches = result.matches
    matches_payload = {
        "session_id": state.session_id,
        "query": build_query(state),
        "matches": result.matches,
        "note": _no_match_note(state, result),
        "from_related_fields": result.from_related_fields,
        "guidance": build_guidance(state, result.matches),
    }
    yield _frame(SSEEventType.UNIVERSITY_MATCHES, matches_payload)
    await _save_artifact(
        user,
        thread_id,
        kind="university_matches",
        summary=f"{len(result.matches)} matching programme(s)",
        payload=matches_payload,
    )


def _no_match_note(state: SessionState, result: MatchResult) -> str | None:
    """Say what the index was searched for, so an empty grid is not a mystery."""
    shortfall = result.shortfall
    if shortfall is None:
        return None

    slots = state.slots
    # Written out, so the note reads "close enough to Artificial Intelligence"
    # rather than "close enough to Ai" - and names the subject the search
    # actually looked for.
    subject = expand_field(slots.field_of_study) or "your subject"

    if shortfall == "subject":
        # Programmes exist that they qualify for, but none are in their field.
        # Listing them anyway is what produced data-science degrees for an
        # English Literature graduate, so they are withheld and explained.
        return (
            f"Nothing in the course index is close enough to {subject} to be "
            "worth recommending. There are programmes you qualify for, but "
            "they are in other disciplines, and a degree in the wrong subject "
            "is not a shortlist. Ingest course pages in your field and they "
            "will appear here."
        )

    where = slots.target_country or "your destination"
    wanted = target_degree_levels(slots.education_level)
    level = f" at {wanted[0]} level" if wanted else ""

    if shortfall == "requirements":
        # The courses are there; the student does not clear their bar. Saying
        # the catalogue is empty would be false, and would hide the one thing
        # they can actually act on - which the report above already names.
        count = result.catalogue_count
        plural = "" if count == 1 else "s"
        gaps: list[str] = []
        held = slots.language_score.overall if slots.language_score else None
        if result.lowest_ielts_required and (
            held is None or held < result.lowest_ielts_required
        ):
            have = f"you have {held:g}" if held is not None else "you have not sat it"
            gaps.append(
                f"IELTS {result.lowest_ielts_required:g} ({have})"
            )
        card = state.last_card
        percent = card.conversion.normalized_percentage if card else None
        if result.lowest_gpa_required and (
            percent is None or percent < result.lowest_gpa_required
        ):
            have = f"yours converts to {percent:g}%" if percent is not None else ""
            gaps.append(
                f"{result.lowest_gpa_required:g}% academic{f' ({have})' if have else ''}"
            )

        reason = (
            " The least demanding asks for " + " and ".join(gaps) + "."
            if gaps
            else " None of them accepts your profile as it stands."
        )
        return (
            f"There {'is' if count == 1 else 'are'} {count} programme{plural} in "
            f"{where}{level} in the index, but you do not yet meet the entry "
            f"requirements.{reason} This is about the bar, not the catalogue - "
            "closing that gap puts them in reach."
        )

    return (
        f"Nothing in the course index is in {where}{level} yet. The index only "
        "holds programmes that have been crawled, so this is a gap in the "
        "catalogue rather than anything about your grades - your report above "
        "stands. Widen the destination, or ingest the course pages you care "
        "about."
    )


def _restrict_to_confirmation(
    patch: SlotPatch, state: SessionState
) -> tuple[SlotPatch, list[SlotName]]:
    """Keep only the confirmation itself and corrections to pending values.

    Returns the trimmed patch plus the slots that were set aside, so the reply
    can tell the student their answer was heard but not yet recorded. Silently
    dropping it would look like the agent simply ignored them.
    """
    pending = set(state.slots.pending_confirmation())
    allowed = SlotPatch(confirms_ocr=patch.confirms_ocr)
    deferred: list[SlotName] = []

    for name in SlotName:
        value = getattr(patch, name.value)
        if value is None:
            continue
        if name in pending:
            # A correction to a value under review is exactly what we want.
            setattr(allowed, name.value, value)
        else:
            deferred.append(name)

    return allowed, deferred


def _plan_turn(
    state: SessionState,
    *,
    had_upload: bool,
    slots_changed: bool = False,
    noise: bool = False,
    deferred: list[SlotName] | None = None,
    ambiguous_country: str | None = None,
    multi_country: list[str] | None = None,
    same_country_as_home: str | None = None,
    grade_change: AcademicScore | None = None,
    awaiting_transcript: bool = False,
) -> tuple[str, str, Any]:
    """Build the directive + deterministic fallback, and the card when unlocked.

    `had_upload` is True only when a transcript was parsed *successfully* this
    turn, so a failed scan never gets thanked for. `slots_changed` says whether
    this turn learned anything, `noise` that the message was unreadable, and
    `deferred` names slots the student offered while a transcript review was
    still outstanding - heard, but deliberately not recorded yet.
    """
    slots = state.slots
    missing = slots.missing()
    to_confirm = slots.pending_confirmation()

    # Unreadable input: answer it directly instead of pattern-matching onward.
    if noise:
        wanted = (
            " Then ask again for " + " and ".join(SLOT_QUESTIONS[n] for n in missing[:2])
            if missing
            else ""
        )
        directive = (
            "The student's last message does not read as words — it looks like "
            "stray keystrokes. Say kindly, in one sentence, that you did not "
            f"catch that and ask them to type it again.{wanted}. "
            "Do not answer as though it were a real question, and do not repeat "
            "any diagnostic figures."
        )
        fallback = (
            "Sorry, I could not make sense of that one."
            + (
                " Could you type it again? I still need "
                + " and ".join(SLOT_QUESTIONS[n] for n in missing[:2])
                + "."
                if missing
                else " Could you rephrase it for me?"
            )
        )
        state.awaiting = missing[:2]
        return directive, fallback, None

    known = ", ".join(
        f"{SLOT_LABELS[name]}={_render(getattr(slots, name.value))}"
        for name in SlotName
        if getattr(slots, name.value) is not None
    ) or "nothing yet"

    # Confirmation gate: OCR-derived values are unlocked only once acknowledged.
    if to_confirm:
        confirm_list = ", ".join(
            f"{SLOT_LABELS[name]}: {_render(getattr(slots, name.value))}"
            for name in to_confirm
        )
        # Confirmation is a question on its own. Piling the next questions on
        # top of it buries the values the student is meant to be checking, and
        # invites them to answer the easy question and skip the review. The
        # remaining fields are asked on the following turn, once they reply.
        if ambiguous_country:
            held = (
                f" The student also said just {ambiguous_country}, which could be "
                "their citizenship or their destination. Do not assume which. "
                "Say in half a sentence that you will sort that out once the "
                "transcript details are confirmed."
            )
        elif deferred:
            held = (
                " The student also mentioned their "
                + " and ".join(SLOT_LABELS[n] for n in deferred)
                + ". Acknowledge that in half a sentence and say you will note it "
                "straight after they confirm - do not treat it as answered."
            )
        else:
            held = ""
        directive = (
            f"I read these values off the student's transcript: {confirm_list}. "
            "Read them back in one short sentence and ask whether they are "
            "correct. Ask nothing else at all this turn - no other fields, no "
            f"follow-up questions - and do not list what is still missing.{held} "
            "Wait for their answer."
        )
        if ambiguous_country:
            preface = (
                f"I will come back to {ambiguous_country} in a moment. "
            )
        elif deferred:
            preface = (
                "Thanks - I will note your "
                + " and ".join(SLOT_LABELS[n] for n in deferred)
                + " once we are done here. "
            )
        else:
            preface = ""
        fallback = (
            preface
            + f"I have read your transcript — I picked up {confirm_list}. "
            "Does that all look right?"
        )
        # Nothing is being asked for, so a bare reply this turn is a yes/no or a
        # correction, not a slot answer.
        state.awaiting = []
        return directive, fallback, None

    if awaiting_transcript:
        directive = (
            "The student has asked for their transcript to be read but has not "
            "attached it yet. Reply with ONE short sentence confirming you will "
            "read it once they share it. Do not ask for their name, their "
            "country, their grade, or anything else - the document carries "
            "those, and asking reads as not having listened. Do not list what "
            "you will extract. Stop after that one sentence."
        )
        fallback = (
            "I can certainly help you look through your transcript once you "
            "share it with me."
        )
        # The next message is the upload, or a question about it - not an
        # answer to a slot nobody asked for.
        state.awaiting = []
        return directive, fallback, None

    if grade_change is not None:
        was = _describe_score(state.slots.cgpa)
        now = _describe_score(grade_change)
        directive = (
            f"The student already gave their grade as {was}, and has now said "
            f"{now}. Do not record the new one yet and do not claim to have "
            "updated anything. Ask, in one short sentence, whether they want "
            f"to replace {was} with {now}. A yes replaces it; a no keeps the "
            "original."
        )
        fallback = (
            f"You already told me {was}. Do you want to change that to {now}?"
        )
        # The next reply answers this question, not a slot in the usual order.
        state.awaiting = []
        return directive, fallback, None

    if same_country_as_home:
        directive = (
            f"The student named {same_country_as_home} as where they want to "
            "study, but that is also the country they hold citizenship in - so "
            "it would not be studying abroad at all. That is usually a mistyped "
            "or repeated answer. Do not record it and do not assume either way. "
            "Ask in one short sentence whether they really mean studying inside "
            f"{same_country_as_home}, or whether they meant a different country. "
            "A yes means they meant it; otherwise they will name somewhere else."
        )
        fallback = (
            f"You already hold citizenship in {same_country_as_home}, so "
            f"studying there would not be studying abroad. Did you mean "
            f"{same_country_as_home} itself, or a different country?"
        )
        state.awaiting = []
        return directive, fallback, None

    if multi_country:
        listed = _list_countries(multi_country)
        directive = (
            f"The student named more than one destination: {listed}. Do not "
            "record any of them yet and do not claim to have noted them. Ask, "
            "in one short sentence, whether they would like the shortlist to "
            f"cover all of {listed}, or just one - and if one, which. Say that "
            "searching several is fine."
        )
        fallback = (
            f"You mentioned {listed}. Shall I search all of them, or would you "
            "rather focus on one? Either is fine - just say yes, or name the "
            "one you want."
        )
        # The next reply answers this question, not a slot in the usual order.
        state.awaiting = []
        return directive, fallback, None

    if ambiguous_country:
        directive = (
            f"The country {ambiguous_country} is unassigned and the student's "
            "last message did not settle where it belongs. Do not guess, do not "
            "record it, and do not claim to have noted it. In one short "
            f"sentence, {_country_question(ambiguous_country, state)}. Invite "
            "them to answer with the word citizenship or the word study."
        )
        fallback = _country_question_fallback(ambiguous_country, state) + (
            ' Reply with "citizenship" or "study" and I will record it.'
        )
        # The next reply answers this question, not a slot in the usual order.
        state.awaiting = []
        return directive, fallback, None

    if missing:
        asking = missing[:2]
        state.awaiting = asking
        wanted = " and ".join(SLOT_QUESTIONS[name] for name in asking)
        directive = (
            f"Known so far: {known}. Still missing: "
            f"{', '.join(SLOT_LABELS[n] for n in missing)}. "
            f"Acknowledge what they just said, then ask for {wanted}. "
            "Ask for nothing else. The fields listed as missing are the only "
            "ones that exist - there is no budget, funding, scholarship, "
            "start date, work-experience or preferred-university field, and "
            "asking for one invents a requirement the student then thinks "
            "they have to meet. "
            "The known list is the only record: never state a value as settled "
            "just because it came up earlier in the conversation. If something "
            "was mentioned but is not in that list, it was not recorded - ask "
            "for it rather than repeating it back as fact. "
            "Do not produce any diagnostic report yet." + NO_INVENTED_SPECIFICS
        )
        opener = (
            "Thanks for the transcript! " if had_upload else ""
        ) or ("" if state.messages else GREETING + " ")
        fallback = f"{opener}To get your diagnostic report, could you tell me {wanted}?"
        return directive, fallback, None

    # Every field present — compute the card before streaming so the summary
    # can quote real numbers instead of improvising them.
    try:
        card = build_card(state)
    except (ConversionError, DiagnosticsUnavailable) as exc:
        logger.info("Diagnostics deferred for %s: %s", state.session_id, exc)
        directive = (
            "I could not convert the student's grade because the scale is unclear. "
            "Ask them what the maximum possible grade on their transcript is "
            "(for example 4.0, 10.0 or 100%)."
        )
        fallback = (
            "Almost there — what is the maximum possible grade on your transcript "
            "(4.0, 10.0, or 100%)? I need it to convert your CGPA accurately."
        )
        state.awaiting = [SlotName.CGPA]
        return directive, fallback, None

    # The report is produced once. Re-sending the card on every later message
    # would re-announce results the student is already looking at, and would
    # answer an unrelated question with a wall of numbers.
    #
    # The test is the card's *contents*, not whether a slot was touched: asking
    # "shortlist some universities" makes the extractor re-state the country it
    # already knows, and a re-stated value used to count as a change and print
    # a second, identical report. A genuine correction - a fixed CGPA, a new
    # destination - still produces a new card, because that one differs.
    if state.diagnostics_unlocked and _same_report(card, state.last_card):
        directive = (
            "The diagnostic report has already been delivered and is on screen; "
            "every onboarding field is collected. Answer the student's message "
            "conversationally as their advisor. Do not restate the converted "
            "grades unless they ask for them, and do not re-run the report. "
            + SHORTLIST_DIRECTIVE
        )
        fallback = (
            "Your diagnostic report and programme shortlist are above. Ask me "
            "anything about them."
        )
        state.awaiting = []
        return directive, fallback, None

    conversion = card.conversion
    directive = (
        "Every onboarding field is collected. Give a short, encouraging summary "
        "of where "
        "this student stands academically, using exactly these system-computed "
        f"figures: normalised percentage {conversion.normalized_percentage:g}%, "
        f"US GPA {conversion.us_gpa:g} ({conversion.us_letter}), German grade "
        f"{conversion.german_grade:g} ({conversion.german_label}), UK "
        f"{conversion.uk_classification.value}, ECTS {conversion.ects_grade}. "
        # Every confirmed destination, not just the primary. Naming one after
        # the student asked for two left the model to improvise cover for the
        # other, which is where the invented universities came from.
        f"Destinations the student has confirmed: "
        f"{_list_countries(state.slots.destinations())}. "
        f"Key points to weave in: {' '.join(card.eligibility_notes[:3])} "
        "Do not recompute anything. End by telling them a detailed card and "
        "matching programmes are shown below." + SHORTLIST_DIRECTIVE
    )
    state.awaiting = []
    # This is the reply, not a backup for one: the report turn does not go
    # through the model. Every figure here is the computed conversion, and the
    # destinations are the ones actually recorded - so the prose cannot drift
    # from the card and grid printed underneath it.
    where = _list_countries(state.slots.destinations())
    fallback = (
        f"Here is where you stand, {state.slots.full_name or 'there'}. Your "
        f"{conversion.source_value:g} converts to "
        f"{conversion.normalized_percentage:g}% overall — a "
        f"{conversion.us_gpa:g} US GPA ({conversion.us_letter}), a German "
        f"{conversion.german_grade:g} ({conversion.german_label}), and a UK "
        f"{conversion.uk_classification.value}. The card below breaks it down "
        "system by system"
        + (f", and the programmes matched for {where} follow underneath it."
           if where else ", and the matching programmes follow underneath it.")
    )
    return directive, fallback, card


SCALE_SUFFIX: Final[dict[str, str]] = {
    "percentage": "%",
    "us_4_0": "/4.0",
    "scale_5_0": "/5.0",
    "scale_10_0": "/10.0",
    "scale_20_0": "/20.0",
    "german_1_5": " (German scale)",
    "unknown": "",
}


def _same_report(card: DiagnosticCardPayload, previous: DiagnosticCardPayload | None) -> bool:
    """Would this card tell the student anything the last one did not?

    Only the conversion is compared. The card is a report about a *grade*:
    the percentage, the US GPA, the German and UK equivalents. Saying "I want
    to study business instead" changes none of those numbers, yet comparing
    whole payloads treated it as a new report - so the card was reprinted in
    full every time the student refined what they were looking for, which is
    exactly the turn where they want the shortlist, not the arithmetic again.

    A corrected CGPA or nationality does move the conversion, and that does
    warrant a fresh card.
    """
    if previous is None:
        return False
    return card.conversion.model_dump() == previous.conversion.model_dump()


def _render(value: Any) -> str:
    """Compact human rendering of a slot value, for prompts and confirmations."""
    if value is None:
        return "?"
    if isinstance(value, EducationLevel):
        return value.label
    if hasattr(value, "raw_value"):
        return f"{value.raw_value:g}{SCALE_SUFFIX.get(value.scale.value, '')}"
    if hasattr(value, "test"):
        overall = getattr(value, "overall", None)
        return f"{value.test.value}{f' {overall:g}' if overall is not None else ''}"
    return str(value)


def _slot_snapshot(state: SessionState) -> dict[str, Any]:
    slots = state.slots
    return {
        "session_id": state.session_id,
        "slots": slots.model_dump(mode="json", exclude={"ocr_derived", "user_confirmed"}),
        "filled": [n.value for n in SlotName if getattr(slots, n.value) is not None],
        "missing": [n.value for n in slots.missing()],
        "pending_confirmation": [n.value for n in slots.pending_confirmation()],
        "is_complete": slots.is_complete(),
    }


def _session_snapshot(state: SessionState) -> dict[str, Any]:
    return {
        **_slot_snapshot(state),
        "diagnostics_unlocked": state.diagnostics_unlocked,
        "transcript": state.transcript.model_dump(mode="json") if state.transcript else None,
        "last_card": state.last_card.model_dump(mode="json") if state.last_card else None,
        "last_matches": state.last_matches,
        "transcript_parsed": state.transcript_parsed,
        "messages": [m.model_dump(mode="json") for m in state.messages],
    }


def _frame(event: SSEEventType, data: dict[str, Any]) -> str:
    return SSEEvent(event=event, data=data).format()
