"""FastAPI application: the streaming chat endpoint that drives Phase 1.

`POST /api/chat/stream` accepts either JSON (`{session_id, message}`) or
multipart form data (the same fields plus a `file` transcript) and answers with
an SSE stream carrying:

    status             transient progress ("parsing your transcript")
    token              assistant text, streamed
    slot_update        the current state of the onboarding fields
    transcript_parsed  structured OCR output for the upload
    diagnostic_card    the Phase 1 conversion card (JSON payload)
    error              a user-safe failure message
    done               terminal frame, carries the session id
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any, Final

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse

from .config import get_settings
from .diagnostics import DiagnosticsUnavailable, build_card
from .gpa_converter import ConversionError
from .llm_service import (
    TurnStatus,
    bare_country,
    extract_slots,
    is_affirmation,
    is_negation,
    looks_like_noise,
    resolve_country_role,
    title_name,
    same_country,
    states_country_role,
    stream_reply,
)
from .ocr_service import TranscriptParseError, parse_transcript
from .scope import ScopeVerdict, classify, refusal_directive
from .schemas import (
    ChatRequest,
    EducationLevel,
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


async def _read_request(request: Request) -> tuple[str | None, str, Upload | None]:
    """Return (session_id, message, upload) from a JSON or multipart request."""
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
        if not message and upload is None:
            raise HTTPException(
                status_code=422,
                detail="Send a message, a file, or both.",
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
async def chat_stream(request: Request) -> StreamingResponse:
    session_id, message, upload = await _read_request(request)
    store = get_store(request)
    state = await store.load_or_create(session_id)

    return StreamingResponse(
        _event_stream(state, message, upload, store),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # stop nginx from buffering the stream
            "X-Session-Id": state.session_id,
        },
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
) -> AsyncIterator[str]:
    """Drive one turn: ingest, fill slots, stream a reply, maybe emit a card."""
    turn = TurnStatus()
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
                yield _frame(SSEEventType.TOKEN, {"text": token})
            state.append("assistant", "".join(reply_parts))
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
        deferred: list[SlotName] = []
        ambiguous_country: str | None = None
        if message:
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

            # A lone country name is ambiguous while both country slots are
            # open: "Germany" could be citizenship or destination. Guessing
            # produces a confident, wrong profile, so ask instead.
            elif (
                candidate := bare_country(message)
            ) is not None and _country_is_ambiguous(candidate, state):
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
            changed = state.slots.merge(patch)
            if changed or patch.confirms_ocr:
                slots_changed = True
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
            same_country_as_home=state.pending_same_country,
        )

        # 5. Stream the assistant's reply.
        reply_parts = []
        async for token in stream_reply(
            state, directive + SCOPE_REMINDER, fallback=fallback, status=turn
        ):
            reply_parts.append(token)
            yield _frame(SSEEventType.TOKEN, {"text": token})
        state.append("assistant", "".join(reply_parts))

        # 6. Emit the diagnostic card once the barrier is cleared.
        if card is not None:
            state.diagnostics_unlocked = True
            state.last_card = card
            yield _frame(SSEEventType.DIAGNOSTIC_CARD, card.model_dump(mode="json"))

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
    same_country_as_home: str | None = None,
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
            "The known list is the only record: never state a value as settled "
            "just because it came up earlier in the conversation. If something "
            "was mentioned but is not in that list, it was not recorded - ask "
            "for it rather than repeating it back as fact. "
            "Do not produce any diagnostic report yet."
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
    if state.diagnostics_unlocked and not slots_changed:
        directive = (
            "The diagnostic report has already been delivered and is on screen; "
            "every onboarding field is collected. Answer the student's message "
            "conversationally as their advisor. Do not restate the converted "
            "grades unless they ask for them, and do not re-run the report."
        )
        fallback = (
            "Your diagnostic report is above. Ask me anything about it — or say "
            "the word and I will put together a university shortlist next."
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
        f"Target country: {state.slots.target_country}. "
        f"Key points to weave in: {' '.join(card.eligibility_notes[:3])} "
        "Do not recompute anything. End by telling them a detailed card is shown "
        "below and asking if they want a university shortlist next."
    )
    state.awaiting = []
    fallback = (
        f"Here is where you stand, {state.slots.full_name or 'there'}. Your "
        f"{conversion.source_value:g} converts to {conversion.normalized_percentage:g}% "
        f"overall — a {conversion.us_gpa:g} US GPA, a German {conversion.german_grade:g} "
        f"({conversion.german_label}), and a UK {conversion.uk_classification.value}. "
        "The card below breaks it down system by system."
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
        "messages": [m.model_dump(mode="json") for m in state.messages],
    }


def _frame(event: SSEEventType, data: dict[str, Any]) -> str:
    return SSEEvent(event=event, data=data).format()
