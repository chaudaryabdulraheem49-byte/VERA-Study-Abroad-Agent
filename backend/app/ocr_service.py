"""Transcript parsing via a vision model (GPT-4o / Gemini) or LlamaParse.

Two providers behind one async entry point, `parse_transcript`:

* `vision`     — images go straight to the configured vision model; PDFs are
  rasterised page by page first (pypdfium2), because the chat-completions image
  input accepts images only. Works with OpenAI and with Gemini, which is reached
  through its OpenAI-compatible endpoint.
* `llamaparse` — the document is uploaded, the job polled to completion, and
  the returned markdown is then structured by a cheap text model.

Both paths converge on an `ExtractedTranscript`. Failures raise
`TranscriptParseError` with a message that is safe to show a student.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import re
from typing import Any, Final

from .config import get_settings
from .gpa_converter import weighted_cumulative
from .llm_service import get_client
from .schemas import ExtractedTranscript, GradingScale

logger = logging.getLogger(__name__)

MAX_PDF_PAGES: Final = 6
PDF_RENDER_SCALE: Final = 2.0  # ~144 DPI: legible small print without huge payloads

EXTRACTION_INSTRUCTIONS: Final = """You are a transcript parser for a study-abroad advisory service.

Read the academic transcript and return ONLY a JSON object with these keys:
{
  "student_name": string|null,
  "institution_name": string|null,
  "program_name": string|null,
  "field_of_study": string|null,
  "education_level": "high_school"|"diploma"|"bachelors"|"masters"|"doctorate"|null,
  "subjects": [{"name": string, "grade": string|null, "credits": number|null,
                "numeric_grade": number|null, "passed": boolean|null}],
  "cumulative_gpa": number|null,
  "gpa_scale_max": number|null,
  "percentage": number|null,
  "grading_scale": "percentage"|"us_4_0"|"scale_5_0"|"scale_10_0"|"scale_20_0"|"german_1_5"|"unknown",
  "total_credits": number|null,
  "backlogs": integer,
  "failed_subjects": [string],
  "gap_years": number|null,
  "graduation_year": integer|null,
  "confidence": number between 0 and 1,
  "warnings": [string]
}

Rules:
- Transcribe only what is printed. Never estimate a GPA that is not shown; \
leave it null and note it in "warnings".
- The final cumulative result is normally printed at the very end of a \
transcript - the last rows of the last page, a summary block, or a footer - \
rather than beside the subject list. Read the bottom of the document before \
concluding that no overall grade is stated. It may be labelled CGPA, \
Cumulative GPA, Overall GPA, Final CGPA, Aggregate or Grand Total, and may \
sit in a summary table with total credits earned.
- Per-semester or per-year totals are not the cumulative figure. When several \
are shown, "cumulative_gpa" is the final overall one, not the latest \
semester's.
- "gpa_scale_max" is the maximum possible GPA stated on the document (4.0, \
5.0, 10.0, 20.0 or 100 for percentages).
- "education_level" comes from the programme name: "BS/BSc/BA/BFA/BE/BTech" \
is bachelors, "MS/MSc/MA/MBA" is masters, "PhD" is doctorate, and an \
Intermediate/FSc/A-level/12th-grade certificate is high_school. Use null if \
the document does not say.
- Count as backlogs any subject marked F, FAIL, RE-APPEAR, ABSENT, INCOMPLETE \
or supplementary, and list their names in "failed_subjects".
- Infer "gap_years" only from a visible break of a year or more between \
enrolment periods; otherwise null.
- "confidence" reflects legibility and completeness of the document.
- If the document is not an academic transcript, return every field null/empty \
with confidence 0 and a warning saying so."""


class TranscriptParseError(RuntimeError):
    """Raised when a document cannot be turned into an `ExtractedTranscript`."""


# --------------------------------------------------------------------------- #
# Upload validation
# --------------------------------------------------------------------------- #


def validate_upload(filename: str, content_type: str | None, size: int) -> str:
    """Check type and size, returning the resolved MIME type."""
    settings = get_settings()
    resolved = (content_type or "").split(";")[0].strip().lower()

    if not resolved or resolved == "application/octet-stream":
        lowered = filename.lower()
        if lowered.endswith(".pdf"):
            resolved = "application/pdf"
        elif lowered.endswith((".jpg", ".jpeg")):
            resolved = "image/jpeg"
        elif lowered.endswith(".png"):
            resolved = "image/png"
        elif lowered.endswith(".webp"):
            resolved = "image/webp"

    if resolved not in settings.allowed_upload_types:
        raise TranscriptParseError(
            "That file type is not supported. Please upload your transcript as a "
            "PDF, PNG or JPG."
        )
    if size <= 0:
        raise TranscriptParseError("The uploaded file was empty.")
    if size > settings.max_upload_bytes:
        limit_mb = settings.max_upload_bytes / (1024 * 1024)
        raise TranscriptParseError(
            f"That file is larger than {limit_mb:.0f} MB. Please upload a smaller scan."
        )
    return resolved


# --------------------------------------------------------------------------- #
# Public entry point
# --------------------------------------------------------------------------- #


async def parse_transcript(
    content: bytes,
    filename: str,
    content_type: str | None = None,
) -> ExtractedTranscript:
    """Parse one transcript document into structured fields."""
    mime = validate_upload(filename, content_type, len(content))
    settings = get_settings()

    if settings.ocr_provider == "llamaparse" and settings.llamaparse_api_key:
        transcript = await _parse_with_llamaparse(content, filename, mime)
    else:
        transcript = await _parse_with_vision(content, filename, mime)

    return _post_process(transcript)


def _is_about_missing_cgpa(note: str) -> bool:
    """True when a model-written warning already says the total is absent.

    Matched on meaning rather than wording, because the phrasing varies run to
    run: "not explicitly stated as a single final value", "no cumulative GPA
    found", "CGPA is not printed". Deliberately narrow - a warning about
    anything else, such as grades shown for unfinished courses, must survive,
    since that one explains a genuinely different problem.
    """
    lowered = note.lower()
    mentions_total = any(
        term in lowered for term in ("cgpa", "cumulative gpa", "overall gpa")
    )
    says_absent = any(
        term in lowered
        for term in ("not explicitly", "not stated", "not printed", "not shown",
                     "no cumulative", "no overall", "not available", "absent",
                     "could not find", "not found", "not provided")
    )
    return mentions_total and says_absent


def _post_process(transcript: ExtractedTranscript) -> ExtractedTranscript:
    """Derive what the document left implicit, without inventing grades."""
    if transcript.cumulative_gpa is None and transcript.percentage is None:
        derived = weighted_cumulative(transcript.subjects)
        if derived is not None:
            transcript.cumulative_gpa = derived
            transcript.cumulative_gpa_computed = True
            # The model usually notes the missing total itself, in its own
            # words. Appending this unconditionally printed the same fact
            # twice, which reads as two separate problems rather than one.
            # Replace its version, since only this one says what was done
            # about it and what the student should check.
            transcript.warnings = [
                note for note in transcript.warnings if not _is_about_missing_cgpa(note)
            ]
            transcript.warnings.append(
                "No overall CGPA was printed on this document, so it was "
                "averaged from the subject grades. Your official CGPA may "
                "differ - please check it against your transcript."
            )

    if not transcript.backlogs and transcript.failed_subjects:
        transcript.backlogs = len(transcript.failed_subjects)

    if transcript.total_credits is None:
        credits = [s.credits for s in transcript.subjects if s.credits]
        if credits:
            transcript.total_credits = round(sum(credits), 2)

    if (
        transcript.grading_scale is GradingScale.UNKNOWN
        and transcript.cumulative_gpa is None
        and transcript.percentage is None
    ):
        transcript.warnings.append(
            "No cumulative grade could be read from this document."
        )
    return transcript


# --------------------------------------------------------------------------- #
# Provider: vision model (GPT-4o / Gemini)
# --------------------------------------------------------------------------- #


async def _parse_with_vision(
    content: bytes, filename: str, mime: str
) -> ExtractedTranscript:
    client = get_client()
    if client is None:
        raise TranscriptParseError(
            "Document parsing is not configured on this server. Please type your "
            "CGPA and field of study instead."
        )

    if mime == "application/pdf":
        images = await asyncio.to_thread(_render_pdf_pages, content)
        parts = [
            {"type": "image_url", "image_url": {"url": _data_url(page, "image/png"), "detail": "high"}}
            for page in images
        ]
    else:
        parts = [
            {"type": "image_url", "image_url": {"url": _data_url(content, mime), "detail": "high"}}
        ]

    settings = get_settings()
    try:
        response = await asyncio.wait_for(
            client.chat.completions.create(
                model=settings.vision_model,
                messages=[
                    {"role": "system", "content": EXTRACTION_INSTRUCTIONS},
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": (
                                    f"Transcript file: {filename}. Extract the fields "
                                    "described in your instructions as JSON."
                                ),
                            },
                            *parts,
                        ],
                    },
                ],
                temperature=0.0,
                max_tokens=8000,
                response_format={"type": "json_object"},
            ),
            timeout=settings.ocr_timeout_seconds,
        )
    except TimeoutError as exc:
        raise TranscriptParseError(
            "Reading that document took too long. Please try a smaller or clearer scan."
        ) from exc
    except Exception as exc:
        from .llm_service import is_rate_limited

        if is_rate_limited(exc):
            logger.warning("Vision parsing hit the provider rate limit: %s", exc)
            raise TranscriptParseError(
                "I am being rate limited by the AI provider. Please wait about a "
                "minute and upload your transcript again."
            ) from exc
        logger.exception("Vision parsing failed for %s", filename)
        raise TranscriptParseError(
            "I could not read that document. Please try a clearer scan, or type "
            "your details instead."
        ) from exc

    payload = _loads(response.choices[0].message.content)
    return _build(payload, parser=get_settings().vision_parser_name)


def _data_url(blob: bytes, mime: str) -> str:
    return f"data:{mime};base64,{base64.b64encode(blob).decode('ascii')}"


def _render_pdf_pages(content: bytes) -> list[bytes]:
    """Rasterise the first `MAX_PDF_PAGES` pages to PNG bytes (blocking)."""
    try:
        import pypdfium2 as pdfium
    except ImportError as exc:  # pragma: no cover - dependency is declared
        raise TranscriptParseError(
            "PDF support is unavailable on this server. Please upload a PNG or "
            "JPG photo of your transcript."
        ) from exc

    try:
        document = pdfium.PdfDocument(content)
    except Exception as exc:
        raise TranscriptParseError(
            "That PDF could not be opened. It may be corrupted or password protected."
        ) from exc

    # Which pages, when there are more than the cap allows.
    #
    # Taking the first N dropped the last page, and the final cumulative total
    # is printed at the end of a transcript - so on any document longer than
    # the cap the one figure that matters was guaranteed to be missing, and
    # the grade got averaged from subjects instead. The tail is kept for that
    # reason; the opening pages carry the name, institution and programme.
    total = len(document)
    if total <= MAX_PDF_PAGES:
        indices = list(range(total))
    else:
        indices = list(range(MAX_PDF_PAGES - 1)) + [total - 1]

    pages: list[bytes] = []
    try:
        for index in indices:
            page = document[index]
            bitmap = page.render(scale=PDF_RENDER_SCALE)
            buffer = bitmap.to_pil()
            import io

            sink = io.BytesIO()
            buffer.save(sink, format="PNG")
            pages.append(sink.getvalue())
    finally:
        document.close()

    if not pages:
        raise TranscriptParseError("That PDF appears to have no pages.")
    return pages


# --------------------------------------------------------------------------- #
# Provider: LlamaParse
# --------------------------------------------------------------------------- #


async def _parse_with_llamaparse(
    content: bytes, filename: str, mime: str
) -> ExtractedTranscript:
    settings = get_settings()
    markdown = await _llamaparse_markdown(content, filename, mime)

    client = get_client()
    if client is None:
        raise TranscriptParseError(
            "Document parsing is only half-configured on this server (no LLM key)."
        )
    try:
        response = await client.chat.completions.create(
            model=settings.extraction_model,
            messages=[
                {"role": "system", "content": EXTRACTION_INSTRUCTIONS},
                {
                    "role": "user",
                    "content": f"Transcript ({filename}) as markdown:\n\n{markdown[:60000]}",
                },
            ],
            temperature=0.0,
            response_format={"type": "json_object"},
        )
    except Exception as exc:
        logger.exception("LlamaParse post-processing failed for %s", filename)
        raise TranscriptParseError(
            "I read the document but could not structure it. Please type your "
            "CGPA and field of study instead."
        ) from exc

    return _build(_loads(response.choices[0].message.content), parser="llamaparse")


async def _llamaparse_markdown(content: bytes, filename: str, mime: str) -> str:
    """Upload to LlamaParse, poll the job, and return the markdown result."""
    import httpx

    settings = get_settings()
    headers = {"Authorization": f"Bearer {settings.llamaparse_api_key}"}
    base = settings.llamaparse_base_url.rstrip("/")

    async with httpx.AsyncClient(timeout=settings.ocr_timeout_seconds) as http:
        try:
            upload = await http.post(
                f"{base}/upload",
                headers=headers,
                files={"file": (filename, content, mime)},
                data={"parsing_instruction": "Preserve every grade table verbatim."},
            )
            upload.raise_for_status()
            job_id = upload.json()["id"]
        except Exception as exc:
            logger.exception("LlamaParse upload failed for %s", filename)
            raise TranscriptParseError(
                "The document service rejected that upload. Please try again."
            ) from exc

        deadline = asyncio.get_running_loop().time() + settings.ocr_timeout_seconds
        while True:
            if asyncio.get_running_loop().time() > deadline:
                raise TranscriptParseError(
                    "Reading that document took too long. Please try a smaller file."
                )
            await asyncio.sleep(settings.llamaparse_poll_interval)
            try:
                status = await http.get(f"{base}/job/{job_id}", headers=headers)
                status.raise_for_status()
                state = str(status.json().get("status", "")).upper()
            except Exception as exc:
                logger.exception("LlamaParse polling failed for job %s", job_id)
                raise TranscriptParseError(
                    "The document service stopped responding. Please try again."
                ) from exc

            if state in {"SUCCESS", "COMPLETED"}:
                break
            if state in {"ERROR", "FAILED", "CANCELLED"}:
                raise TranscriptParseError(
                    "The document service could not parse that file. Please upload "
                    "a clearer scan."
                )

        try:
            result = await http.get(f"{base}/job/{job_id}/result/markdown", headers=headers)
            result.raise_for_status()
            return str(result.json().get("markdown", ""))
        except Exception as exc:
            logger.exception("LlamaParse result fetch failed for job %s", job_id)
            raise TranscriptParseError(
                "The parsed document could not be retrieved. Please try again."
            ) from exc


# --------------------------------------------------------------------------- #
# Shared response handling
# --------------------------------------------------------------------------- #


_FENCE_RE: Final = re.compile(r"^\s*```(?:json)?\s*|\s*```\s*$", re.IGNORECASE)


def _loads(raw: str | None) -> dict[str, Any]:
    """Parse the model's JSON, tolerating the ways models wrap it."""
    if not raw or not raw.strip():
        raise TranscriptParseError(
            "The document reader returned nothing. Please try uploading again."
        )

    text = _FENCE_RE.sub("", raw.strip())
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        # Models occasionally add a sentence before or after the object; take
        # the outermost braces and retry before giving up.
        start, end = text.find("{"), text.rfind("}")
        if start != -1 and end > start:
            try:
                payload = json.loads(text[start : end + 1])
            except json.JSONDecodeError as exc:
                raise _unreadable(raw, exc) from exc
        else:
            raise _unreadable(raw, None)
    if not isinstance(payload, dict):
        raise TranscriptParseError("The parser returned an unexpected structure.")
    return payload


def _unreadable(raw: str, exc: Exception | None) -> TranscriptParseError:
    """Log enough to diagnose, and tell the student something true.

    Truncated output is the usual cause, and it is not a scan-quality problem -
    saying "try a clearer scan" sends people off to rescan a perfectly good
    document, so the message names the real situation instead.
    """
    truncated = not raw.rstrip().endswith("}")
    logger.error(
        "Transcript JSON unparseable (len=%d, truncated=%s, error=%s). "
        "First 300 chars: %.300s | Last 200 chars: %.200s",
        len(raw),
        truncated,
        exc,
        raw,
        raw[-200:],
    )
    if truncated:
        return TranscriptParseError(
            "That transcript was too long for me to read in one pass. Please "
            "upload just the pages with your grades and overall CGPA."
        )
    return TranscriptParseError(
        "I could not read the details out of that document. Please type your "
        "CGPA and field of study, and I will take it from there."
    )


def _build(payload: dict[str, Any], *, parser: str) -> ExtractedTranscript:
    payload["parser"] = parser
    try:
        return ExtractedTranscript.model_validate(payload)
    except ValueError:
        # One bad field (a negative credit, a GPA of 0) should not lose the
        # whole extraction: retry with the offending values dropped.
        logger.warning("Strict transcript validation failed; retrying leniently.")
        cleaned = {
            key: value
            for key, value in payload.items()
            if key
            not in {"cumulative_gpa", "percentage", "gpa_scale_max", "subjects", "gap_years"}
        }
        cleaned["parser"] = parser
        cleaned.setdefault("warnings", []).append(
            "Some values on this transcript could not be validated and were dropped."
        )
        try:
            return ExtractedTranscript.model_validate(cleaned)
        except ValueError as exc:
            raise TranscriptParseError(
                "That document did not look like an academic transcript."
            ) from exc
