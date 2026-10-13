"""Step 1 + 2: crawl a university page and structure it into a validated object.

Crawl4AI renders the page (these are JS-heavy sites), reduces it to
`fit_markdown` — the main content with navigation, headers and footers
stripped — and an `LLMExtractionStrategy` turns that into JSON shaped by
`CourseExtractionSchema`. Pydantic then validates it, so nothing reaches the
database that the schema would reject.

Crawl4AI is imported lazily: it pulls in Playwright and a browser download, so
the rest of the app (and the test suite) must not require it to be installed.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Final

from pydantic import ValidationError

from ...config import get_settings
from ...llm_service import is_rate_limited
from .schemas import CourseExtractionSchema

logger = logging.getLogger(__name__)

_MAX_MARKDOWN_CHARS: Final = 60_000

EXTRACTION_INSTRUCTION: Final = """You are reading one university course page.

Extract exactly one course as JSON matching the provided schema.

Rules:
- Transcribe only what the page states. Never estimate a tuition figure, a GPA
  bar or an IELTS band that is not printed.
- tuition_fee_amount is the annual figure for an international student, as a
  number. currency is its ISO code (EUR, CAD, AUD, USD, GBP).
- tuition_fee_usd: convert only if the page itself gives a USD figure;
  otherwise leave it 0 and the pipeline will convert.
- min_gpa_percent is on a 0-100 scale. Convert a stated GPA: "3.0/4.0" is 75,
  "2:1 honours" is 60. Use 0 when the page states no academic minimum.
- min_ielts_score is the overall band (0-9). Use 0 when none is stated.
- deadline_date must be YYYY-MM-DD, or null for rolling or unstated deadlines.
  Never invent a date.
- post_study_work_eligible: true only where the page says graduates may work in
  the country afterwards (post-study work visa, stay-back, OPT).
- syllabus_description: the substantive course content - modules, structure,
  specialisations, duration. This is what students are matched against, so
  prefer detail over brevity, and do not pad it with admissions boilerplate.

If the page is not a single course page (a listing, a faculty index, an error
page), return an empty JSON object: {}"""


class CrawlError(RuntimeError):
    """Raised when a page could not be crawled or structured."""


class TransientExtractionError(RuntimeError):
    """The provider was briefly unavailable; retrying is worthwhile.

    Crawl4AI catches provider failures and returns them as an "error" block
    rather than raising, so a 503 or a 429 looks identical to "this page has
    no course on it" unless the block contents are inspected.
    """


_TRANSIENT_MARKERS: Final = (
    "503",
    "429",
    "unavailable",
    "high demand",
    "rate limit",
    "resource_exhausted",
    "overloaded",
    "timeout",
    "timed out",
)


def _is_transient(message: str) -> bool:
    lowered = message.lower()
    return any(marker in lowered for marker in _TRANSIENT_MARKERS)


async def extract_course_from_url(
    url: str, *, retries: int | None = None
) -> CourseExtractionSchema:
    """Crawl one course page and return a validated course object.

    Raises `CrawlError` when the page cannot be fetched, the model returns
    nothing usable, or the result fails schema validation.
    """
    settings = get_settings()
    attempts = settings.crawl_max_retries if retries is None else retries
    crawler_cls, run_config = _build_crawl4ai(url)

    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            payload = await asyncio.wait_for(
                _run_once(crawler_cls, url, run_config),
                timeout=settings.crawl_timeout_seconds,
            )
            return _validate(payload, url)
        except CrawlError:
            raise  # a structural problem; retrying will not help
        except TimeoutError as exc:
            last_error = exc
            logger.warning(
                "Crawl timed out for %s (attempt %d/%d)", url, attempt, attempts
            )
        except TransientExtractionError as exc:
            last_error = exc
            delay = 3.0 * (2 ** (attempt - 1))
            logger.warning(
                "Provider unavailable for %s (attempt %d/%d); retrying in %.0fs: %s",
                url,
                attempt,
                attempts,
                delay,
                exc,
            )
            await asyncio.sleep(delay)
        except Exception as exc:  # noqa: BLE001 - browser + provider SDKs
            last_error = exc
            if is_rate_limited(exc):
                delay = 2.0 * (2 ** (attempt - 1))
                logger.warning(
                    "Extraction rate limited for %s; retrying in %.0fs", url, delay
                )
                await asyncio.sleep(delay)
            else:
                logger.warning(
                    "Crawl failed for %s (attempt %d/%d): %s",
                    url,
                    attempt,
                    attempts,
                    exc,
                )

    raise CrawlError(f"Could not crawl {url} after {attempts} attempts: {last_error}")


async def extract_courses(
    urls: list[str], *, concurrency: int = 4
) -> tuple[list[CourseExtractionSchema], dict[str, str]]:
    """Crawl many pages concurrently.

    Returns the courses that succeeded and a `{url: reason}` map of those that
    did not - a bulk ingest should not abort because one page moved.
    """
    semaphore = asyncio.Semaphore(concurrency)
    failures: dict[str, str] = {}

    async def one(target: str) -> CourseExtractionSchema | None:
        async with semaphore:
            try:
                return await extract_course_from_url(target)
            except Exception as exc:  # noqa: BLE001
                failures[target] = str(exc)
                logger.error("Skipping %s: %s", target, exc)
                return None

    results = await asyncio.gather(*(one(u) for u in urls))
    return [course for course in results if course is not None], failures


# --------------------------------------------------------------------------- #
# Crawl4AI wiring
# --------------------------------------------------------------------------- #


def _build_crawl4ai(url: str) -> tuple[Any, Any]:
    """Assemble the crawler class and run config, importing Crawl4AI lazily."""
    try:
        from crawl4ai import (  # noqa: PLC0415 - optional heavy dependency
            AsyncWebCrawler,
            CacheMode,
            CrawlerRunConfig,
            LLMConfig,
        )
        from crawl4ai.extraction_strategy import LLMExtractionStrategy
    except ImportError as exc:  # pragma: no cover - depends on install
        raise CrawlError(
            "crawl4ai is not installed. Run `pip install -r requirements.txt` "
            "and then `python -m playwright install chromium`."
        ) from exc

    settings = get_settings()
    if not settings.llm_enabled:
        raise CrawlError(
            "No LLM provider configured - extraction needs GEMINI_API_KEY or "
            "OPENAI_API_KEY."
        )

    # Crawl4AI routes through LiteLLM, which wants a provider-prefixed name.
    # LiteLLM's `gemini/` route talks to Google's *native* API and builds its
    # own URL, so handing it our OpenAI-compatibility base_url makes every
    # call 404 with a bare GeminiException. Only OpenAI-style providers take
    # an override here.
    if settings.llm_provider == "gemini":
        provider = f"gemini/{settings.crawler_model}"
        base_url = None
        # LiteLLM warns that temperature below 1.0 degrades Gemini 3 reasoning
        # and can send it into loops; determinism is not worth that here.
        temperature = 1.0
    else:
        provider = f"openai/{settings.crawler_model}"
        base_url = settings.base_url
        temperature = 0.0

    strategy = LLMExtractionStrategy(
        llm_config=LLMConfig(
            provider=provider,
            api_token=settings.api_key,
            base_url=base_url,
        ),
        schema=CourseExtractionSchema.model_json_schema(),
        extraction_type="schema",
        instruction=EXTRACTION_INSTRUCTION,
        # fit_markdown is the point of using Crawl4AI here: it drops nav,
        # cookie banners and footers, so the model reads course content
        # instead of the site chrome that surrounds it.
        input_format="fit_markdown",
        apply_chunking=False,
        extra_args={"temperature": temperature},
    )

    run_config = CrawlerRunConfig(
        extraction_strategy=strategy,
        cache_mode=CacheMode.BYPASS,
        page_timeout=int(settings.crawl_timeout_seconds * 1000),
        wait_until="domcontentloaded",
        word_count_threshold=20,
    )
    return AsyncWebCrawler, run_config


async def _run_once(crawler_cls: Any, url: str, run_config: Any) -> Any:
    """One crawl + extraction pass, returning the raw extracted content."""
    async with crawler_cls(verbose=False) as crawler:
        result = await crawler.arun(url=url, config=run_config)

    if not getattr(result, "success", False):
        raise RuntimeError(getattr(result, "error_message", "crawl reported failure"))

    extracted = getattr(result, "extracted_content", None)
    if not extracted:
        # No selector to blame - fit_markdown found nothing the model could use.
        markdown = _fit_markdown(result)
        if not markdown:
            raise CrawlError(
                f"{url} yielded no readable content. The page may be behind a "
                "login, a bot check, or rendered entirely by a script that did "
                "not finish loading."
            )
        raise CrawlError(f"{url} was readable but the model extracted nothing.")
    return extracted


def _fit_markdown(result: Any) -> str:
    """Pull fit_markdown across the shapes different Crawl4AI versions use."""
    markdown = getattr(result, "markdown", None)
    for attribute in ("fit_markdown", "raw_markdown"):
        value = getattr(markdown, attribute, None)
        if isinstance(value, str) and value.strip():
            return value[:_MAX_MARKDOWN_CHARS]
    if isinstance(markdown, str):
        return markdown[:_MAX_MARKDOWN_CHARS]
    return ""


def _validate(raw: Any, url: str) -> CourseExtractionSchema:
    """Parse the strategy's output into a validated course.

    The strategy returns a JSON string, and usually a *list* of blocks even
    with chunking off, so unwrap before validating.
    """
    payload = raw
    if isinstance(payload, (str, bytes)):
        try:
            payload = json.loads(payload)
        except json.JSONDecodeError as exc:
            raise CrawlError(f"{url}: extraction returned non-JSON output") from exc

    if isinstance(payload, list):
        blocks = [item for item in payload if isinstance(item, dict)]
        errors = [item for item in blocks if item.get("error")]
        candidates = [item for item in blocks if not item.get("error")]
        if not candidates:
            # Surface what the provider actually said - a 503 is worth another
            # attempt, a malformed page is not.
            detail = " ".join(str(item.get("content", "")) for item in errors).strip()
            if detail and _is_transient(detail):
                raise TransientExtractionError(f"{url}: {detail[:200]}")
            raise CrawlError(
                f"{url}: extraction returned no usable block"
                + (f" ({detail[:200]})" if detail else "")
            )
        payload = max(candidates, key=lambda item: len(json.dumps(item)))

    if not isinstance(payload, dict) or not payload:
        raise CrawlError(f"{url}: page did not look like a single course page")

    payload.pop("index", None)
    payload.pop("error", None)
    payload.setdefault("source_url", url)

    try:
        return CourseExtractionSchema.model_validate(payload)
    except ValidationError as exc:
        missing = ", ".join(
            ".".join(str(part) for part in error["loc"]) for error in exc.errors()
        )
        raise CrawlError(
            f"{url}: extracted data failed validation ({missing}). The page "
            "probably does not state these fields."
        ) from exc
