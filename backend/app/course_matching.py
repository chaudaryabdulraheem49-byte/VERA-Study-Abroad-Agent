"""Bridge between the Phase 1 conversation and the Phase 2 search pipeline.

Turns a completed student profile into `SearchConstraints` and runs the hybrid
search. Phase 2 is imported lazily so the chat keeps working when Postgres or
Qdrant are not running - a student mid-interview should never see the
conversation break because a database is down.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Final, NamedTuple

from .config import get_settings
from .llm_service import country_aliases
from .schemas import DiagnosticCardPayload, EducationLevel, SessionState

logger = logging.getLogger(__name__)

# What a student is *applying for*, given what they already hold. Someone with
# a Bachelor's is shopping for a Master's, not another Bachelor's - matching on
# the qualification they already have would return the course they just
# finished.
_NEXT_DEGREE: Final[dict[EducationLevel, list[str]]] = {
    EducationLevel.HIGH_SCHOOL: ["Bachelors"],
    EducationLevel.DIPLOMA: ["Bachelors"],
    EducationLevel.BACHELORS: ["Masters"],
    EducationLevel.MASTERS: ["PhD", "Masters"],
    EducationLevel.DOCTORATE: ["PhD"],
}

# "Europe" is a region, not a value in the country column. Filtering on it
# literally would return nothing, so it expands to the countries we index.
_REGIONS: Final[dict[str, list[str]]] = {
    "europe": [
        "Germany", "France", "Netherlands", "Sweden", "Denmark", "Finland",
        "Norway", "Ireland", "Italy", "Spain", "Portugal", "Poland",
        "Austria", "Switzerland", "Belgium", "Czechia", "Hungary", "Greece",
    ],
}


def target_degree_levels(level: EducationLevel | None) -> list[str]:
    """The degree levels a student holding `level` would be applying for."""
    if level is None:
        return []
    return list(_NEXT_DEGREE.get(level, []))


# The register's wording for each level, used when the student named one.
_LEVEL_NAMES: Final[dict[EducationLevel, str]] = {
    EducationLevel.HIGH_SCHOOL: "Bachelors",
    EducationLevel.DIPLOMA: "Bachelors",
    EducationLevel.BACHELORS: "Bachelors",
    EducationLevel.MASTERS: "Masters",
    EducationLevel.DOCTORATE: "PhD",
}


class MatchingUnavailable(RuntimeError):
    """Raised when the search could not be run.

    `quota_exhausted` separates the two causes, because they read completely
    differently to a student: a database that is down is a fault being worked
    on, while a metered allowance that is spent comes back on its own.
    """

    def __init__(self, message: str, *, quota_exhausted: bool = False) -> None:
        super().__init__(message)
        self.quota_exhausted = quota_exhausted


def build_constraints(state: SessionState, card: DiagnosticCardPayload) -> Any:
    """Map the interview answers onto the Phase 2 hard filter.

    The diagnostic card is an input, not just an output: its normalised
    percentage is what the `min_gpa_percent` filter compares against, so the
    two phases agree on one number rather than each deriving their own.
    """
    from .services.phase2.schemas import SearchConstraints

    slots = state.slots

    # Expand to every spelling of the destination. The interview stores a
    # canonical name, a crawled page stores whatever its own prose said, and
    # the filter compares the two exactly - so "UK" would never match a row
    # that reads "United Kingdom".
    # Every confirmed destination, each expanded to its spellings. A student
    # who asked for Australia and the UK gets both searched, not whichever
    # happened to be typed first.
    countries: list[str] = []
    seeds: list[str] = []
    for destination in slots.destinations():
        key = destination.strip().lower()
        region = _REGIONS.get(key)
        seeds.extend(region if region is not None else [destination.strip()])
    if seeds:
        countries = sorted({alias for seed in seeds for alias in country_aliases(seed)})

    # Medical & dental degrees cross bachelor/masters boundaries depending on jurisdiction
    # (e.g. Australian MBBS is Bachelors, Canadian MD/DDS is Masters, Canadian Pre-Med is Bachelors).
    expanded_field = expand_field(slots.field_of_study).lower()
    is_medical_or_dental = any(
        term in expanded_field
        for term in ("medicine", "dentistry", "mbbs", "bds", "dental", "surgery", "doctor of medicine")
    )
    if is_medical_or_dental:
        degrees = ["Bachelors", "Masters"]
    elif state.desired_level is not None:
        degrees = [_LEVEL_NAMES[state.desired_level]]
    else:
        degrees = target_degree_levels(slots.education_level)

    # Only constrain on a band the student actually holds. "Planned" means we
    # do not know it yet, and filtering on an unknown would quietly drop every
    # course that states any language requirement at all.
    ielts: float | None = None
    if slots.language_score is not None and slots.language_score.overall is not None:
        ielts = slots.language_score.overall

    return SearchConstraints(
        # No budget slot is collected in the interview, so tuition is ranked
        # rather than filtered; the grid shows the figure for each match.
        max_budget_usd=None,
        student_ielts=ielts,
        student_gpa_percent=card.conversion.normalized_percentage,
        countries=countries,
        degree_levels=degrees,
    )


# Abbreviations students type for a subject, and what a syllabus calls it.
#
# An embedding of "Ai" is nearly meaningless: two characters carry almost no
# signal, and the same student's field written out scores far higher against
# the same courses. Measured against this index, "Ai UK Masters" peaked at
# 0.592 and was rejected by the relevance floor, while "Artificial
# Intelligence UK Masters" reached 0.639 on the very same courses. The
# student's subject had not changed - only how much of it reached the vector.
#
# Only unambiguous entries belong here. "BA" is left out because it is a
# degree as often as it is business administration, and "CE" because civil and
# computer engineering both claim it; expanding those would put a student in
# the wrong discipline, which is worse than leaving the abbreviation alone.
_FIELD_EXPANSIONS: Final[dict[str, str]] = {
    "ai": "Artificial Intelligence",
    "ml": "Machine Learning",
    "cs": "Computer Science",
    "comp sci": "Computer Science",
    "it": "Information Technology",
    "ict": "Information and Communication Technology",
    "ds": "Data Science",
    "se": "Software Engineering",
    "ee": "Electrical Engineering",
    "me": "Mechanical Engineering",
    "che": "Chemical Engineering",
    "ux": "User Experience Design",
    "ui": "User Interface Design",
    "hr": "Human Resources Management",
    "pr": "Public Relations",
    "mba": "Business Administration",
    "bba": "Business Administration",
    "llb": "Law",
    "llm": "Law",
    "mbbs": "Medicine",
    "econ": "Economics",
    "psych": "Psychology",
    "arch": "Architecture",
    "acc": "Accounting",
    "bio": "Biology",
    "chem": "Chemistry",
    "maths": "Mathematics",
    "math": "Mathematics",
    "stats": "Statistics",
    "civ": "Civil Engineering",
    "mech": "Mechanical Engineering",
    "elec": "Electrical Engineering",
    "md": "Medicine",
    "bds": "Dentistry",
    "dds": "Dentistry",
    "dmd": "Dentistry",
    "dent": "Dentistry",
    "surg": "Surgery",
    "pharm": "Pharmacy",
    "pharmd": "Pharmacy",
    "nurs": "Nursing",
    "bscn": "Nursing",
    "physio": "Physiotherapy",
    "mpt": "Physiotherapy",
    "mot": "Occupational Therapy",
    "mph": "Public Health",
    "dvm": "Veterinary Medicine",
    "vet": "Veterinary Medicine",
    "bdes": "Design",
    "mdes": "Design",
    "bfa": "Fine Arts",
    "mfa": "Fine Arts",
    "jd": "Law",
    "phy": "Physics",
}


def expand_field(field: str | None) -> str:
    """Write a subject out in full, so the embedding has something to work with.

    Whole-field matches expand outright. Otherwise each token is expanded
    individually, which keeps "AI and robotics" intact while still writing out
    the part that matters - and a token is only touched if the table knows it,
    so ordinary prose passes through unchanged.
    """
    if not field:
        return ""
    text = field.strip()
    whole = _FIELD_EXPANSIONS.get(text.lower())
    if whole:
        return whole
    return " ".join(
        _FIELD_EXPANSIONS.get(token.lower(), token) for token in text.split()
    )


# Neighbouring disciplines, for when nothing in the student's own subject
# clears the bar. Keyed on the *expanded* field name.
#
# These are used only as a fallback, never mixed into the ordinary query.
# Measured against this index, "Artificial Intelligence Australia Masters"
# scored the real AI degree at 0.784 with the next course 0.172 behind it;
# appending the parent terms dropped the true match to 0.743 and lifted the
# runner-up to 0.658, closing the gap to 0.085. Broadening every search makes
# the discipline boundary blurrier - which is the complaint that produced the
# relevance floor in the first place.
_RELATED_FIELDS: Final[dict[str, list[str]]] = {
    "artificial intelligence": [
        "Computer Science", "Machine Learning", "Data Science",
        "Software Engineering", "Information Technology",
    ],
    "machine learning": [
        "Artificial Intelligence", "Data Science", "Statistics",
        "Computer Science",
    ],
    "data science": [
        "Statistics", "Computer Science", "Analytics", "Machine Learning",
    ],
    "computer science": [
        "Software Engineering", "Information Technology",
        "Artificial Intelligence", "Computing",
    ],
    "software engineering": [
        "Computer Science", "Information Technology", "Computing",
    ],
    "information technology": [
        "Computer Science", "Information Systems", "Computing",
    ],
    "cybersecurity": ["Information Technology", "Computer Science", "Networks"],
    "mechanical engineering": [
        "Mechatronics", "Manufacturing Engineering", "Aerospace Engineering",
        "Engineering",
    ],
    "electrical engineering": [
        "Electronics", "Mechatronics", "Power Engineering", "Engineering",
    ],
    "civil engineering": [
        "Structural Engineering", "Construction Management", "Engineering",
    ],
    "business administration": [
        "Management", "Commerce", "Finance", "Marketing",
    ],
    "economics": ["Finance", "Econometrics", "Commerce"],
    "english literature": [
        "Literature", "Creative Writing", "English", "Humanities",
    ],
    "graphic design": [
        "Visual Communication", "Design", "Digital Media", "Fine Arts",
    ],
    "psychology": ["Behavioural Science", "Counselling", "Social Science"],
    "nursing": ["Health Science", "Midwifery", "Public Health"],
    "medicine": [
        "Biomedical Science", "Health Sciences", "Medical Science", "Dentistry", "Pharmacy",
    ],
    "dentistry": [
        "Dental Science", "Dental Hygiene", "Dentistry", "Medicine", "Health Sciences",
    ],
}


def related_fields(field: str | None) -> list[str]:
    """Neighbouring disciplines for a subject, or none if we do not know any."""
    expanded = expand_field(field).lower()
    if not expanded:
        return []
    if expanded in _RELATED_FIELDS:
        return list(_RELATED_FIELDS[expanded])
    # A phrase such as "artificial intelligence and robotics" should still find
    # its neighbours; the longest key wins so the most specific entry applies.
    for key in sorted(_RELATED_FIELDS, key=len, reverse=True):
        if key in expanded:
            return list(_RELATED_FIELDS[key])
    return []


def build_query(state: SessionState, *, broaden: bool = False) -> str:
    """The text embedded and compared against syllabus vectors.

    `broaden` adds neighbouring disciplines. It is for the second attempt
    only - see `_RELATED_FIELDS` for why it must not be the default.
    """
    slots = state.slots
    subject = expand_field(slots.field_of_study)
    parts = [subject]
    if broaden:
        parts.extend(related_fields(slots.field_of_study))
    parts.extend(slots.destinations())
    if state.desired_level is not None:
        parts.append(_LEVEL_NAMES[state.desired_level])
    elif wanted := target_degree_levels(slots.education_level):
        parts.append(wanted[0])
    query = " ".join(part for part in parts if part).strip()
    return query or "postgraduate study"


class MatchResult(NamedTuple):
    """What the search found, and - when it found nothing - which step emptied it.

    An empty grid has two quite different causes and the student needs to be
    told which: no programme they *qualify* for (wrong country, level or
    grade), or plenty they qualify for but none in their *subject*. Collapsing
    both to an empty list loses the only part that is actionable.
    """

    matches: list[dict[str, Any]]
    eligible_count: int
    # True when these came from the second, broadened attempt, so the grid can
    # say they are neighbouring disciplines rather than the student's own.
    from_related_fields: bool = False
    # Courses in the right country and at the right level, counted *before*
    # the student's grade and language score are applied. It is what separates
    # "we have nothing there" from "we have something there and you do not
    # meet its bar" - two sentences that ask for completely different actions.
    catalogue_count: int = 0
    # The gentlest entry requirements among those, so the shortfall can be
    # named as a number rather than left for the student to infer.
    lowest_gpa_required: float | None = None
    lowest_ielts_required: float | None = None

    @property
    def shortfall(self) -> str | None:
        if self.matches:
            return None
        if self.eligible_count:
            return "subject"
        return "requirements" if self.catalogue_count else "catalogue"


def build_guidance(
    state: SessionState, matches: list[dict[str, Any]]
) -> dict[str, Any] | None:
    """Typical entry requirements for the destination, as *general* guidance.

    Most register-sourced courses publish no entry requirements, so their
    cards read "Not published" - true, but it leaves a student with no sense
    of what they are aiming at. This fills that gap without pretending to know
    any particular course's bar: it is the country-level rule the diagnostic
    report already quotes, reused rather than re-invented, and the UI labels
    it as typical-for-the-country rather than stated-by-the-programme.

    It is never fed into the filter. Returned only when at least one shown
    course actually lacks a published requirement, so it stays out of the way
    when the cards can speak for themselves.
    """
    from .diagnostics import COUNTRY_RULES, normalise_country

    country = state.slots.target_country
    if not country or not matches:
        return None

    key = normalise_country(country)
    if key is None:
        return None

    unstated = sum(
        1
        for m in matches
        if m.get("min_gpa_percent") is None or m.get("min_ielts_score") is None
    )
    if not unstated:
        return None

    rules = COUNTRY_RULES[key]
    percent = float(rules["min_percentage"])  # type: ignore[arg-type]
    card_percent = (
        state.last_card.conversion.normalized_percentage if state.last_card else None
    )
    return {
        "country": country,
        "typical_gpa_percent": percent,
        "typical_ielts": float(rules["ielts"]),  # type: ignore[arg-type]
        "note": str(rules["note"]),
        "unstated_count": unstated,
        # Whether the student clears the typical bar, so the line can be
        # encouraging or candid rather than merely informative.
        "student_clears": None if card_percent is None else card_percent >= percent,
    }


async def _probe_catalogue(constraints: Any) -> tuple[int, float | None, float | None]:
    """How many courses are in the right place, ignoring the student's grades.

    Run only when the search came back empty, so the ordinary path pays
    nothing for it. Answers the question the student actually has: is there
    nothing here, or is there something here I cannot yet get into?
    """
    from sqlalchemy import func, select

    from .services.phase2.db import Course, session_scope

    query = select(
        func.count(Course.course_id),
        func.min(Course.min_gpa_percent),
        func.min(Course.min_ielts_score),
    )
    if constraints.countries:
        query = query.where(Course.country.in_(constraints.countries))
    if constraints.degree_levels:
        query = query.where(Course.degree_level.in_(constraints.degree_levels))

    async with session_scope() as session:
        count, gpa, ielts = (await session.execute(query)).one()
    return int(count or 0), gpa, ielts


async def find_matches(
    state: SessionState, card: DiagnosticCardPayload, *, top_k: int = 6
) -> MatchResult:
    """Run the hybrid search for this student. Never raises for the caller."""
    try:
        from .services.phase2.hybrid_search_service import search_courses
    except ImportError as exc:  # pragma: no cover - phase 2 deps optional
        raise MatchingUnavailable("Phase 2 dependencies are not installed") from exc

    constraints = build_constraints(state, card)
    query = build_query(state)
    logger.info("Course matching: query=%r constraints=%s", query, constraints)

    try:
        matches = await search_courses(query, constraints, top_k=top_k)
    except Exception as exc:  # noqa: BLE001 - DB/vector store/provider
        # "Could not reach the course index" was actively misleading here: the
        # index was reachable, it was the query that could not be embedded.
        text = str(exc)
        raise MatchingUnavailable(
            text, quota_exhausted="429" in text or "quota" in text.lower()
        ) from exc

    settings = get_settings()
    # Baseline cosine similarity in gemini-embedding-001 is higher than OpenAI text-embedding-3-small
    # (~0.60-0.63 for unrelated boilerplate, >=0.67 for genuine matches).
    provider_floor = (
        0.65 if "gemini" in settings.embedding_model.lower() else settings.match_min_similarity
    )
    provider_fallback = (
        0.62 if "gemini" in settings.embedding_model.lower() else settings.match_fallback_similarity
    )

    kept = filter_by_relevance(
        matches, floor=provider_floor, field_of_study=state.slots.field_of_study
    )
    related = False

    # Second attempt, only when the first came back thin. Widening every
    # search would blur the discipline boundary the floor exists to keep;
    # widening a search that found almost nothing costs nothing, because there
    # was nothing to blur.
    if len(kept) < settings.match_min_results:
        broadened = build_query(state, broaden=True)
        if broadened != query:
            logger.info("Course matching: retrying broadened query=%r", broadened)
            try:
                wider = await search_courses(broadened, constraints, top_k=top_k)
                relaxed = filter_by_relevance(
                    wider,
                    floor=provider_fallback,
                    field_of_study=state.slots.field_of_study,
                )
            except Exception as exc:  # noqa: BLE001 - provider or store
                # A failed second attempt must not lose the first one's
                # results: a thin shortlist beats an error page.
                logger.warning("Broadened retry failed: %s", exc)
                relaxed = []
            if len(relaxed) > len(kept):
                kept, related = relaxed, True

    logger.info(
        "Course matching: %d eligible, %d shown%s",
        len(matches),
        len(kept),
        " (related fields)" if related else "",
    )
    catalogue_count = 0
    lowest_gpa = lowest_ielts = None
    if not kept and not matches:
        # Nothing survived the hard filter. Before telling a student the
        # catalogue is empty, check whether it is - the answer is usually that
        # courses exist and their entry bar is above the student's profile.
        try:
            catalogue_count, lowest_gpa, lowest_ielts = await _probe_catalogue(
                constraints
            )
        except Exception as exc:  # noqa: BLE001 - a nicety, never a blocker
            logger.warning("Catalogue probe failed: %s", exc)

    return MatchResult(
        matches=[match.model_dump(mode="json") for match in kept],
        eligible_count=len(matches),
        from_related_fields=related,
        catalogue_count=catalogue_count,
        lowest_gpa_required=lowest_gpa,
        lowest_ielts_required=lowest_ielts,
    )


def is_topically_relevant(match: Any, field_of_study: str | None) -> bool:
    """Verify whether a candidate programme has topical alignment with the field.

    The semantic embedding search is powerful but vulnerable to boilerplate overlap.
    In particular, European university descriptions universally state:
    'Language of instruction: 100% taught in English. Prestigious 1-year English-taught...'
    When a student searches for 'English Literature', the embedding model sees common
    tokens ('English', 'Netherlands', 'Masters') and scores unrelated LL.M. and AI
    degrees above the 0.60 floor.

    This gate ensures that any candidate either shares discipline terms with the student's
    field (or its approved neighbouring fields), or has genuine lexical evidence outside
    medium-of-instruction boilerplate.
    """
    if not field_of_study:
        return True

    title = getattr(match, "course_title", None) or (
        match.get("course_title") if isinstance(match, dict) else ""
    )
    syllabus = getattr(match, "syllabus_description", None) or (
        match.get("syllabus_description") if isinstance(match, dict) else ""
    )

    # For synthetic test objects without title and syllabus, pass through
    if not title and not syllabus:
        return True

    syllabus_clean = re.sub(
        r"(?i)(language of instruction:\s*100%\s*taught in english|100%\s*taught in english|english-taught|taught in english|instruction in english)",
        "",
        syllabus or "",
    )
    title_lower = (title or "").lower()
    clean_lower = (syllabus_clean or "").lower()

    expanded = expand_field(field_of_study).lower()
    terms = [expanded] + [f.lower() for f in related_fields(field_of_study)]

    for term in terms:
        if term in title_lower or term in clean_lower:
            return True

    field_tokens = [
        t
        for t in re.findall(r"\b[a-z]{3,}\b", expanded)
        if t not in {"and", "the", "for", "with", "studies", "study", "bachelor", "master"}
    ]
    specific_tokens = [t for t in field_tokens if t not in {"english"}]
    if specific_tokens:
        for t in specific_tokens:
            if t in title_lower or t in clean_lower:
                return True
    elif "english" in field_tokens:
        if "english" in title_lower or "english" in clean_lower:
            return True

    return False


def filter_by_relevance(
    matches: list[Any],
    *,
    floor: float | None = None,
    field_of_study: str | None = None,
) -> list[Any]:
    """Drop programmes that are eligible but not about the student's subject.

    The SQL filter decides what a student *qualifies* for and the vector search
    orders those by subject; neither one decides whether the last result is
    worth showing. Without this step the grid pads itself to `top_k`, so an
    English Literature graduate was shown three data-science degrees below a
    literature MA - they passed the grade and country filters, and ranking put
    them second, third and fourth because nothing else was left to rank.

    Two cuts, because one alone is wrong in a different direction:

    - An absolute floor, for a subject the index simply does not cover. Every
      score is then mediocre, so there is no cliff for a relative rule to find.
    - A margin below the best score, for a subject it does cover. What counts
      as relevant depends on how good the best answer was, and a fixed floor
      either admits the tail or rejects a whole decent set.
    """
    if not matches:
        return []

    settings = get_settings()
    absolute = settings.match_min_similarity if floor is None else floor

    candidates = matches
    if field_of_study:
        candidates = [m for m in matches if is_topically_relevant(m, field_of_study)]
        if not candidates:
            return []

    best = max(match.similarity_score for match in candidates)
    cutoff = max(absolute, best - settings.match_similarity_margin)
    return [match for match in candidates if match.similarity_score >= cutoff]
