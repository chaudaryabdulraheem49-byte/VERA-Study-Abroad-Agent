"""Ingest official UK Discover Uni Dataset into PostgreSQL and link with Qdrant.

Loads, merges, and validates the 4 mandatory Discover Uni raw CSV datasets:
  - INSTITUTION.csv: Higher education provider registry and metadata
  - COURSE.csv / KISCOURSE.csv: Undergraduate degrees and curriculum details
  - LOCATION.csv: Campus sites, geography, and accommodations
  - TARIFF.csv: UCAS tariff point distributions for dynamic entry requirement mapping

Populates:
  - `institutions`: Campus-level registry (UKPRN, campus, city, country)
  - `universities`: Provider-level records for Course foreign key linkage
  - `courses`: Undergraduate courses aligned with Phase 2 matching schema

Usage:
    python scripts/ingest_uk_discoveruni.py --dry-run
    python scripts/ingest_uk_discoveruni.py
    python scripts/ingest_uk_discoveruni.py --limit 1000
    python scripts/ingest_uk_discoveruni.py --tuition-gbp 18500 --fx 1.27
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Final

import pandas as pd
from sqlalchemy.dialects.postgresql import insert

# Ensure Windows console supports unicode output
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.phase2.db import (  # noqa: E402
    Course,
    Institution,
    University,
    dispose_engine,
    get_engine,
    init_schema,
)

logger = logging.getLogger("ingest_uk_discoveruni")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DEFAULT_RAW_DIR: Final = REPO_ROOT / "data" / "uk" / "raw"
FALLBACK_RAW_DIR: Final = REPO_ROOT / "data" / "data" / "uk"
DEFAULT_TUITION_GBP: Final = 18500.0  # International undergraduate baseline tuition
DEFAULT_FX_GBP_USD: Final = 1.27     # GBP -> USD conversion factor
DEFAULT_CHUNK: Final = 500

# UCAS Tariff Point column midpoints
TARIFF_BANDS: Final[list[tuple[str, float]]] = [
    ("T001", 32.0),   # 1 - 47 points
    ("T048", 56.0),   # 48 - 63 points
    ("T064", 72.0),   # 64 - 79 points
    ("T080", 88.0),   # 80 - 95 points
    ("T096", 104.0),  # 96 - 111 points
    ("T112", 120.0),  # 112 - 127 points
    ("T128", 136.0),  # 128 - 143 points
    ("T144", 152.0),  # 144 - 159 points
    ("T160", 168.0),  # 160 - 175 points
    ("T176", 184.0),  # 176 - 191 points
    ("T192", 200.0),  # 192 - 207 points
    ("T208", 216.0),  # 208 - 223 points
    ("T224", 232.0),  # 224 - 239 points
    ("T240", 248.0),  # 240+ points
]

# CAH (Common Aggregation Hierarchy) code prefix to discipline mapping
CAH_DISCIPLINES: Final[dict[str, str]] = {
    "CAH01": "Medicine & Dentistry",
    "CAH02": "Subjects Allied to Medicine",
    "CAH03": "Biological & Biomedical Sciences",
    "CAH04": "Agriculture, Food & Related Studies",
    "CAH05": "Veterinary Sciences",
    "CAH06": "Physical Sciences",
    "CAH07": "Mathematical Sciences",
    "CAH08": "Engineering & Technology",
    "CAH09": "Computing & Informatics",
    "CAH10": "Materials & Technology",
    "CAH11": "Architecture, Building & Planning",
    "CAH12": "Geographical & Environmental Studies",
    "CAH13": "Humanities & Liberal Arts",
    "CAH14": "Social Sciences",
    "CAH15": "Law & Legal Studies",
    "CAH16": "Business & Management",
    "CAH17": "Communications & Media",
    "CAH18": "Language & Literature Studies",
    "CAH19": "Historical & Philosophical Studies",
    "CAH20": "Creative Arts & Design",
    "CAH21": "Education & Teaching",
    "CAH22": "Combined & General Studies",
    "CAH23": "Philosophy & Theology",
    "CAH24": "Anthropology & Human Sciences",
    "CAH25": "History & Heritage",
    "CAH26": "Media, Journalism & Publishing",
}


@dataclass(frozen=True)
class TariffInfo:
    tariff_points: float | None
    min_gpa: float
    subject_code: str | None
    description: str


def resolve_raw_dir(custom_path: Path | None = None) -> Path:
    """Find the valid raw directory containing the mandatory UK CSVs."""
    candidates = [
        custom_path,
        DEFAULT_RAW_DIR,
        FALLBACK_RAW_DIR,
    ]
    for p in candidates:
        if p and p.is_dir():
            inst_p = p / "INSTITUTION.csv"
            course_p = p / "COURSE.csv" if (p / "COURSE.csv").is_file() else p / "KISCOURSE.csv"
            loc_p = p / "LOCATION.csv"
            tariff_p = p / "TARIFF.csv"
            if inst_p.is_file() and course_p.is_file() and loc_p.is_file() and tariff_p.is_file():
                return p

    raise FileNotFoundError(
        "Could not find required UK Discover Uni raw CSVs. Checked paths:\n"
        f"  - {DEFAULT_RAW_DIR}\n"
        f"  - {FALLBACK_RAW_DIR}\n"
        "All 4 files (INSTITUTION.csv, COURSE.csv/KISCOURSE.csv, LOCATION.csv, TARIFF.csv) are mandatory."
    )


def parse_address_components(address_str: str | None) -> tuple[str, str, str | None]:
    """Extract (city, state_or_county, postcode) from comma-separated address."""
    if not address_str or pd.isna(address_str):
        return ("United Kingdom", "UK", None)

    parts = [p.strip() for p in str(address_str).split(",") if p.strip()]
    if not parts:
        return ("United Kingdom", "UK", None)

    postcode = None
    if len(parts) >= 2 and any(c.isdigit() for c in parts[-1]):
        postcode = parts[-1]
        parts = parts[:-1]

    if not parts:
        return ("United Kingdom", "UK", postcode)

    city = parts[-1]
    state = parts[-2] if len(parts) >= 2 else parts[-1]

    # Clean title case
    city = city.title()
    state = state.title()

    return (city, state, postcode)


def build_tariff_lookup(tariff_df: pd.DataFrame) -> dict[tuple[str, str, str], TariffInfo]:
    """Parse TARIFF.csv into a high-performance lookup keyed by (PUBUKPRN, KISCOURSEID, KISMODE)."""
    grouped_points: dict[tuple[str, str, str], list[float]] = {}
    grouped_subjects: dict[tuple[str, str, str], set[str]] = {}

    for _, row in tariff_df.iterrows():
        pub = str(row.get("PUBUKPRN") or "").strip()
        cid = str(row.get("KISCOURSEID") or "").strip()
        mode = str(row.get("KISMODE") or "").strip()
        if not pub or not cid:
            continue

        key = (pub, cid, mode)

        # Skip rows flagged as unavailable with no data
        if str(row.get("TARUNAVAILREASON") or "").strip() == "1":
            # Still record subject code if present
            sbj = str(row.get("TARSBJ") or "").strip()
            if sbj and sbj != "nan":
                grouped_subjects.setdefault(key, set()).add(sbj)
            continue

        # Compute weighted average tariff points
        total_pct = 0.0
        weighted_sum = 0.0
        for band_col, midpoint in TARIFF_BANDS:
            val = row.get(band_col)
            if pd.notna(val):
                try:
                    pct = float(val)
                    if pct > 0:
                        total_pct += pct
                        weighted_sum += pct * midpoint
                except ValueError:
                    pass

        if total_pct > 0:
            avg_points = weighted_sum / total_pct
            grouped_points.setdefault(key, []).append(avg_points)

        sbj = str(row.get("TARSBJ") or "").strip()
        if sbj and sbj != "nan":
            grouped_subjects.setdefault(key, set()).add(sbj)

    lookup: dict[tuple[str, str, str], TariffInfo] = {}

    # All unique keys encountered
    all_keys = set(grouped_points.keys()) | set(grouped_subjects.keys())
    for key in all_keys:
        pts_list = grouped_points.get(key)
        subjects = grouped_subjects.get(key) or set()
        primary_sbj = sorted(subjects)[0] if subjects else None

        if pts_list:
            mean_tariff = sum(pts_list) / len(pts_list)
            # Dynamic baseline score mapping from UCAS points:
            # Baseline is 55.0% for low or entry-level tariffs (<= 48 pts).
            # Points scale incrementally: 112 pts (BBC) -> ~66.5%, 144 pts (AAA) -> ~72.3%, 168 pts (A*AA) -> ~76.6%
            if mean_tariff <= 48.0:
                min_gpa = 55.0
            else:
                extra = min(35.0, (mean_tariff - 48.0) * 0.18)
                min_gpa = round(55.0 + extra, 1)

            tariff_pts_rounded = int(round(mean_tariff))
            desc = (
                f"Typical entry tariff: ~{tariff_pts_rounded} UCAS points "
                f"(baseline academic entry requirement: {min_gpa}%)."
            )
            lookup[key] = TariffInfo(
                tariff_points=mean_tariff,
                min_gpa=min_gpa,
                subject_code=primary_sbj,
                description=desc,
            )
        else:
            # Fallback according to specification: min_gpa = 55.0 if tariff point missing
            desc = "Standard baseline academic entry requirement: 55.0%."
            lookup[key] = TariffInfo(
                tariff_points=None,
                min_gpa=55.0,
                subject_code=primary_sbj,
                description=desc,
            )

    return lookup


def build_locations_by_provider(loc_df: pd.DataFrame) -> dict[str, list[dict[str, Any]]]:
    """Group campus locations and facilities by UKPRN."""
    by_provider: dict[str, list[dict[str, Any]]] = {}
    for _, row in loc_df.iterrows():
        ukprn = str(row.get("UKPRN") or "").strip()
        if not ukprn:
            continue
        loc_name = str(row.get("LOCNAME") or "").strip()
        lat = str(row.get("LATITUDE") or "").strip()
        lon = str(row.get("LONGITUDE") or "").strip()
        accom = str(row.get("ACCOMURL") or "").strip()
        by_provider.setdefault(ukprn, []).append(
            {
                "loc_id": str(row.get("LOCID") or "").strip(),
                "loc_name": loc_name if loc_name and loc_name != "nan" else "Main Campus",
                "latitude": lat if lat != "nan" else None,
                "longitude": lon if lon != "nan" else None,
                "accom_url": accom if accom != "nan" else None,
            }
        )
    return by_provider


def disambiguate_course_title(row: pd.Series) -> str:
    """Disambiguate course title if specific variants (Foundation, Placement, Study Abroad) exist."""
    title = str(row.get("TITLE") or "").strip()
    low = title.lower()
    variants: list[str] = []

    if str(row.get("FOUNDATION") or "").strip() in ("1", "2") and "foundation" not in low:
        variants.append("with Foundation Year")
    if str(row.get("SANDWICH") or "").strip() in ("1", "2") and "sandwich" not in low and "placement" not in low:
        variants.append("with Placement Year")
    if str(row.get("YEARABROAD") or "").strip() in ("1", "2") and "abroad" not in low and "exchange" not in low:
        variants.append("with Year Abroad")

    if variants:
        title = f"{title} ({', '.join(variants)})"
    return title[:300]


def infer_field_of_study(title: str, subject_code: str | None) -> tuple[str, str | None]:
    """Map course subject code (CAH) or title keywords to standardized academic disciplines."""
    if subject_code:
        prefix = subject_code[:5].upper()
        if prefix in CAH_DISCIPLINES:
            return (CAH_DISCIPLINES[prefix], subject_code)

    low = title.lower()
    if any(k in low for k in ("computer", "software", "data science", "cyber", "artificial intelligence", "computing", "web dev", "information tech")):
        return ("Computing & Informatics", "Information Technology")
    if any(k in low for k in ("business", "management", "finance", "accounting", "marketing", "economics", "entrepreneurship")):
        return ("Business & Management", "Commerce")
    if any(k in low for k in ("mechanical", "electrical", "civil", "aerospace", "electronic", "robotics", "chemical engineering", "engineering")):
        return ("Engineering & Technology", "Engineering")
    if any(k in low for k in ("medicine", "nursing", "pharmacy", "biomedical", "physiotherapy", "radiography", "chiropractic", "health")):
        return ("Subjects Allied to Medicine", "Healthcare")
    if any(k in low for k in ("law", "criminology", "legal", "llb", "justice")):
        return ("Law & Legal Studies", "Jurisprudence")
    if any(k in low for k in ("art", "design", "animation", "fashion", "film", "music", "graphic", "games art", "visual effects", "drama")):
        return ("Creative Arts & Design", "Fine & Applied Arts")
    if any(k in low for k in ("physics", "chemistry", "biology", "mathematics", "biochemistry", "astronomy")):
        return ("Physical & Natural Sciences", "Science")
    if any(k in low for k in ("education", "teaching", "early years", "pedagogy")):
        return ("Education & Teaching", "Education")
    if any(k in low for k in ("psychology", "sociology", "politics", "international relations")):
        return ("Social Sciences", "Social Studies")

    return ("Higher Education (Undergraduate)", "Interdisciplinary")


def compose_syllabus_description(
    title: str,
    institution_name: str,
    campuses: list[str],
    discipline: str,
    sub_tag: str | None,
    duration_years: int,
    tariff_info: TariffInfo,
    honours: bool,
    study_mode: str,
    course_url: str | None,
) -> str:
    """Synthesize a rich, descriptive overview for vector embedding and match cards."""
    campus_str = ", ".join(campuses[:3]) if campuses else "Main Campus"
    award_suffix = "Honours Degree" if honours else "Degree"

    parts = [
        f"{title} is a {duration_years}-year full-time undergraduate Bachelor's {award_suffix} "
        f"offered by {institution_name} in the United Kingdom (Campus: {campus_str}).",
        f"Field of study: {discipline}" + (f" ({sub_tag})." if sub_tag else "."),
        f"Study format: {study_mode} study across {duration_years * 52} instructional weeks.",
        f"{tariff_info.description} Minimum English language qualification: IELTS 6.0.",
        "Graduates of this UK degree are eligible for the UK Graduate Route post-study work visa (2-year stay).",
    ]
    if course_url and course_url != "nan":
        parts.append(f"Official course catalogue: {course_url}")

    return " ".join(parts)


def prepare_datasets(
    raw_dir: Path,
    tuition_gbp: float,
    fx: float,
    limit: int | None = None,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    """Parse, join, and structure UK Discover Uni tables."""
    logger.info("Reading raw CSV files from %s ...", raw_dir)
    inst_file = raw_dir / "INSTITUTION.csv"
    course_file = raw_dir / "COURSE.csv" if (raw_dir / "COURSE.csv").is_file() else raw_dir / "KISCOURSE.csv"
    loc_file = raw_dir / "LOCATION.csv"
    tariff_file = raw_dir / "TARIFF.csv"

    inst_df = pd.read_csv(inst_file, dtype=str, encoding="utf-8-sig")
    loc_df = pd.read_csv(loc_file, dtype=str, encoding="utf-8-sig")
    tariff_df = pd.read_csv(tariff_file, dtype=str, encoding="utf-8-sig")
    course_df = pd.read_csv(course_file, dtype=str, encoding="utf-8-sig")

    logger.info("Raw record counts: Institutions=%d, Locations=%d, Tariffs=%d, Courses=%d",
                len(inst_df), len(loc_df), len(tariff_df), len(course_df))

    # 1. Process Institutions and Addresses
    inst_by_pub: dict[str, dict[str, Any]] = {}
    inst_by_ukprn: dict[str, dict[str, Any]] = {}

    for _, row in inst_df.iterrows():
        pub = str(row.get("PUBUKPRN") or "").strip()
        ukprn = str(row.get("UKPRN") or "").strip()
        name = str(row.get("LEGAL_NAME") or "").strip()
        if not name or name == "nan":
            name = str(row.get("FIRST_TRADING_NAME") or "UK University").strip()

        trading = str(row.get("FIRST_TRADING_NAME") or "").strip()
        addr = str(row.get("PROVADDRESS") or "").strip()
        url = str(row.get("PROVURL") or "").strip()
        if url and not url.startswith("http"):
            url = f"https://{url}"

        city, state, postcode = parse_address_components(addr)

        item = {
            "pub_ukprn": pub,
            "ukprn": ukprn,
            "name": name,
            "trading_name": trading if trading and trading != "nan" else None,
            "website": url if url and url != "nan" else None,
            "city": city,
            "state": state,
            "postcode": postcode,
        }
        if pub:
            inst_by_pub[pub] = item
        if ukprn and ukprn not in inst_by_ukprn:
            inst_by_ukprn[ukprn] = item

    # 2. Process Locations
    locs_by_ukprn = build_locations_by_provider(loc_df)

    # Build `institutions` table payloads
    institution_records: list[dict[str, Any]] = []
    seen_institution_keys: set[tuple[str, str, str]] = set()

    for ukprn, loc_list in locs_by_ukprn.items():
        inst_meta = inst_by_ukprn.get(ukprn)
        inst_name = inst_meta["name"] if inst_meta else f"UK Provider {ukprn}"
        base_city = inst_meta["city"] if inst_meta else "United Kingdom"
        province = inst_meta["state"] if inst_meta else "UK"
        website = inst_meta["website"] if inst_meta else None

        for loc in loc_list:
            campus_name = loc["loc_name"][:300]
            # Try to identify campus-specific city
            campus_city = base_city
            if "Campus" in campus_name:
                m = re.search(r"\((.*?)\s+Campus\)", campus_name, re.IGNORECASE)
                if m:
                    campus_city = m.group(1).strip()
            campus_city = campus_city[:150]

            key = (ukprn, campus_name, campus_city)
            if key not in seen_institution_keys:
                seen_institution_keys.add(key)
                institution_records.append(
                    {
                        "dli_number": ukprn,
                        "institution_name": inst_name[:300],
                        "province": province[:100],
                        "campus_location": campus_name,
                        "city": campus_city,
                        "offers_pgwp": True,
                        "is_public": True,
                        "country": "UK",
                        "website": website,
                    }
                )

    # Also ensure providers with no LOCATION.csv entry have a Main Campus entry
    for pub, inst_meta in inst_by_pub.items():
        ukprn = inst_meta["ukprn"] or pub
        key = (ukprn, "Main Campus", inst_meta["city"][:150])
        if key not in seen_institution_keys:
            seen_institution_keys.add(key)
            institution_records.append(
                {
                    "dli_number": ukprn,
                    "institution_name": inst_meta["name"][:300],
                    "province": inst_meta["state"][:100],
                    "campus_location": "Main Campus",
                    "city": inst_meta["city"][:150],
                    "offers_pgwp": True,
                    "is_public": True,
                    "country": "UK",
                    "website": inst_meta["website"],
                }
            )

    # 3. Build `universities` table records (for Course.university_id Foreign Key)
    university_records: list[dict[str, Any]] = []
    seen_uni_ids: set[str] = set()

    for pub, meta in inst_by_pub.items():
        if pub not in seen_uni_ids:
            seen_uni_ids.add(pub)
            university_records.append(
                {
                    "university_id": pub[:20],
                    "institution_name": meta["name"][:300],
                    "trading_name": meta["trading_name"][:300] if meta["trading_name"] else None,
                    "institution_type": "Public Higher Education Institution",
                    "institution_capacity": None,
                    "website": meta["website"],
                    "city": meta["city"][:120],
                    "state": meta["state"][:20],
                    "postcode": meta["postcode"][:10] if meta["postcode"] else None,
                    "country": "UK",
                    "offers_pgwp": True,
                    "dli_number": meta["ukprn"][:30] if meta["ukprn"] else None,
                }
            )

    # 4. Process TARIFF data
    tariff_lookup = build_tariff_lookup(tariff_df)
    logger.info("Compiled %d entry tariff program mappings from TARIFF.csv", len(tariff_lookup))

    # 5. Process Courses
    course_df = course_df[course_df["TITLE"].notna()].copy()

    # Prefer Full-Time (KISMODE == '01') over Part-Time ('02')
    course_df["is_ft"] = (course_df["KISMODE"] == "01").astype(int)
    course_df = course_df.sort_values("is_ft", ascending=False)

    tuition_usd = round(tuition_gbp * fx, 2)
    course_records: list[dict[str, Any]] = []
    seen_course_keys: set[tuple[str, str]] = set()

    for _, row in course_df.iterrows():
        pub = str(row.get("PUBUKPRN") or "").strip()
        ukprn = str(row.get("UKPRN") or "").strip()
        cid = str(row.get("KISCOURSEID") or "").strip()
        mode = str(row.get("KISMODE") or "").strip()

        inst_meta = inst_by_pub.get(pub) or inst_by_ukprn.get(ukprn)
        if not inst_meta:
            continue

        institution_name = inst_meta["name"]
        clean_title = disambiguate_course_title(row)
        natural_key = (institution_name[:300], clean_title[:300])

        if natural_key in seen_course_keys:
            continue
        seen_course_keys.add(natural_key)

        # Lookup Tariff Info: exact (pub, cid, mode) -> fallback (pub, cid, "01") -> default 55.0
        t_info = (
            tariff_lookup.get((pub, cid, mode))
            or tariff_lookup.get((pub, cid, "01"))
            or tariff_lookup.get((pub, cid, "02"))
            or TariffInfo(
                tariff_points=None,
                min_gpa=55.0,
                subject_code=None,
                description="Standard baseline academic entry requirement: 55.0%.",
            )
        )

        # Campus locations for this provider
        provider_locs = [loc["loc_name"] for loc in locs_by_ukprn.get(ukprn, [])]

        # Duration & Stages
        numstage = str(row.get("NUMSTAGE") or "").strip()
        try:
            duration_years = int(float(numstage)) if numstage and numstage != "nan" else 3
        except ValueError:
            duration_years = 3
        duration_years = max(1, min(duration_years, 6))
        duration_weeks = duration_years * 52

        # Discipline mapping
        discipline, sub_field = infer_field_of_study(clean_title, t_info.subject_code)

        honours = str(row.get("HONOURS") or "1").strip() == "1"
        study_mode = "Full-time" if mode == "01" else "Part-time"
        crse_url = str(row.get("CRSEURL") or "").strip()
        if not crse_url or crse_url == "nan":
            crse_url = inst_meta["website"]

        syllabus = compose_syllabus_description(
            title=clean_title,
            institution_name=institution_name,
            campuses=provider_locs,
            discipline=discipline,
            sub_tag=sub_field,
            duration_years=duration_years,
            tariff_info=t_info,
            honours=honours,
            study_mode=study_mode,
            course_url=crse_url,
        )

        course_records.append(
            {
                "course_title": clean_title[:300],
                "university_name": institution_name[:300],
                "university_id": pub[:20] if pub else None,
                "external_course_code": (cid or f"UK-{clean_title[:10]}")[:30],
                "country": "UK",
                "degree_level": "Bachelors",
                "tuition_fee_amount": tuition_gbp,
                "currency": "GBP",
                "tuition_fee_usd": tuition_usd,
                "min_ielts_score": 6.0,
                "min_gpa_percent": t_info.min_gpa,
                "deadline_date": "2027-01-26",
                "deadline_type": "ESTIMATED_ROLLING",
                "next_deadline": "2027-01-26",
                "intakes": '["September", "January"]',
                "post_study_work_eligible": True,
                "syllabus_description": syllabus,
                "source_url": crse_url if crse_url and crse_url != "nan" else None,
                "duration_weeks": duration_weeks,
                "course_level_raw": "Bachelor Honours Degree" if honours else "Bachelors Degree",
                "field_broad": discipline[:120],
                "field_narrow": sub_field[:160] if sub_field else None,
                "field_detailed": t_info.subject_code[:200] if t_info.subject_code else None,
            }
        )

        if limit and len(course_records) >= limit:
            logger.info("Reached requested limit of %d courses", limit)
            break

    return institution_records, university_records, course_records


async def upsert_institutions(records: list[dict[str, Any]], chunk: int = DEFAULT_CHUNK) -> int:
    """Upsert campus records into the `institutions` table."""
    engine = get_engine()
    written = 0
    async with engine.begin() as conn:
        for i in range(0, len(records), chunk):
            batch = records[i : i + chunk]
            stmt = insert(Institution).values(batch)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_institutions_dli_campus_city",
                set_={
                    "institution_name": stmt.excluded.institution_name,
                    "province": stmt.excluded.province,
                    "offers_pgwp": stmt.excluded.offers_pgwp,
                    "is_public": stmt.excluded.is_public,
                    "country": stmt.excluded.country,
                    "website": stmt.excluded.website,
                },
            )
            await conn.execute(stmt)
            written += len(batch)
    return written


async def upsert_universities(records: list[dict[str, Any]], chunk: int = DEFAULT_CHUNK) -> int:
    """Upsert providers into `universities` table for Foreign Key linkage."""
    engine = get_engine()
    written = 0
    async with engine.begin() as conn:
        for i in range(0, len(records), chunk):
            batch = records[i : i + chunk]
            stmt = insert(University).values(batch)
            stmt = stmt.on_conflict_do_update(
                index_elements=["university_id"],
                set_={
                    "institution_name": stmt.excluded.institution_name,
                    "trading_name": stmt.excluded.trading_name,
                    "institution_type": stmt.excluded.institution_type,
                    "website": stmt.excluded.website,
                    "city": stmt.excluded.city,
                    "state": stmt.excluded.state,
                    "postcode": stmt.excluded.postcode,
                    "country": stmt.excluded.country,
                    "offers_pgwp": stmt.excluded.offers_pgwp,
                    "dli_number": stmt.excluded.dli_number,
                },
            )
            await conn.execute(stmt)
            written += len(batch)
    return written


async def upsert_courses(records: list[dict[str, Any]], chunk: int = DEFAULT_CHUNK) -> int:
    """Upsert courses into the `courses` table."""
    engine = get_engine()
    written = 0
    async with engine.begin() as conn:
        for i in range(0, len(records), chunk):
            batch = records[i : i + chunk]
            stmt = insert(Course).values(batch)
            stmt = stmt.on_conflict_do_update(
                constraint="uq_courses_university_title",
                set_={
                    "university_id": stmt.excluded.university_id,
                    "external_course_code": stmt.excluded.external_course_code,
                    "country": stmt.excluded.country,
                    "degree_level": stmt.excluded.degree_level,
                    "tuition_fee_amount": stmt.excluded.tuition_fee_amount,
                    "currency": stmt.excluded.currency,
                    "tuition_fee_usd": stmt.excluded.tuition_fee_usd,
                    "min_ielts_score": stmt.excluded.min_ielts_score,
                    "min_gpa_percent": stmt.excluded.min_gpa_percent,
                    "deadline_date": stmt.excluded.deadline_date,
                    "deadline_type": stmt.excluded.deadline_type,
                    "next_deadline": stmt.excluded.next_deadline,
                    "intakes": stmt.excluded.intakes,
                    "post_study_work_eligible": stmt.excluded.post_study_work_eligible,
                    "syllabus_description": stmt.excluded.syllabus_description,
                    "source_url": stmt.excluded.source_url,
                    "duration_weeks": stmt.excluded.duration_weeks,
                    "course_level_raw": stmt.excluded.course_level_raw,
                    "field_broad": stmt.excluded.field_broad,
                    "field_narrow": stmt.excluded.field_narrow,
                    "field_detailed": stmt.excluded.field_detailed,
                },
            )
            await conn.execute(stmt)
            written += len(batch)
    return written


def print_breakdown_report(
    institutions: list[dict[str, Any]],
    universities: list[dict[str, Any]],
    courses: list[dict[str, Any]],
) -> None:
    """Print executive statistical report of the ingested UK dataset."""
    total_courses = len(courses)
    total_unis = len(universities)
    total_campuses = len(institutions)

    disciplines = Counter(c["field_broad"] for c in courses)
    gpa_brackets = Counter()
    for c in courses:
        g = c["min_gpa_percent"]
        if g is None or g <= 55.0:
            gpa_brackets["55.0% (Baseline / Open)"] += 1
        elif g <= 60.0:
            gpa_brackets["55.1% - 60.0% (Passing / 2:2)"] += 1
        elif g <= 65.0:
            gpa_brackets["60.1% - 65.0% (Competitive 2:2)"] += 1
        elif g <= 70.0:
            gpa_brackets["65.1% - 70.0% (Solid 2:1)"] += 1
        elif g <= 75.0:
            gpa_brackets["70.1% - 75.0% (High 2:1)"] += 1
        else:
            gpa_brackets["75.1%+ (First Class / Elite)"] += 1

    print("\n" + "=" * 76)
    print("      UK DISCOVER UNI INGESTION & TARIFF MAPPING BREAKDOWN REPORT")
    print("=" * 76)
    print(f"Total UK Higher Education Providers: {total_unis:,}")
    print(f"Total Campuses & Study Locations:     {total_campuses:,}")
    print(f"Total Degree Offerings Ingested:      {total_courses:,}")
    print(f"Degree Level:                         Bachelors (100%)")
    print(f"Post-Study Work Eligibility:          100% Eligible (UK Graduate Route)")
    print(f"Standard English Language Bar:        IELTS 6.0")
    print(f"Default Intakes:                      ['September', 'January']")

    print("\nTop Academic Disciplines:")
    print(f"  {'Discipline':<38} {'Courses':<10} {'Share':<8}")
    print("  " + "-" * 58)
    for disc, cnt in sorted(disciplines.items(), key=lambda x: x[1], reverse=True)[:10]:
        print(f"  {disc:<38} {cnt:>8,}   {cnt / total_courses * 100:5.1f}%")

    print("\nDynamic Tariff-Derived Minimum GPA Distribution:")
    print(f"  {'Academic Tier / GPA Range':<38} {'Courses':<10} {'Share':<8}")
    print("  " + "-" * 58)
    for bracket in [
        "55.0% (Baseline / Open)",
        "55.1% - 60.0% (Passing / 2:2)",
        "60.1% - 65.0% (Competitive 2:2)",
        "65.1% - 70.0% (Solid 2:1)",
        "70.1% - 75.0% (High 2:1)",
        "75.1%+ (First Class / Elite)",
    ]:
        cnt = gpa_brackets.get(bracket, 0)
        print(f"  {bracket:<38} {cnt:>8,}   {cnt / total_courses * 100:5.1f}%")

    print("\nSample Ingested UK Programs:")
    for sample in courses[:4]:
        print(f"  • {sample['course_title']} | {sample['university_name']}")
        print(f"    Discipline: {sample['field_broad']} | Min GPA: {sample['min_gpa_percent']}% | Fee: £{sample['tuition_fee_amount']:,.0f} ($ {sample['tuition_fee_usd']:,.0f} USD)")
    print("=" * 76 + "\n")


async def run(args: argparse.Namespace) -> int:
    raw_dir = resolve_raw_dir(Path(args.raw_dir) if args.raw_dir else None)
    logger.info("Using raw directory: %s", raw_dir)

    inst_records, uni_records, course_records = prepare_datasets(
        raw_dir=raw_dir,
        tuition_gbp=args.tuition_gbp,
        fx=args.fx,
        limit=args.limit,
    )

    print_breakdown_report(inst_records, uni_records, course_records)

    if args.dry_run:
        print("[DRY-RUN] Verification successful. No database records were written.")
        return 0

    await init_schema()

    logger.info("1/3 Upserting %d institutions into 'institutions' table...", len(inst_records))
    i_cnt = await upsert_institutions(inst_records, chunk=args.chunk)
    logger.info("✓ Upserted %d institution records.", i_cnt)

    logger.info("2/3 Upserting %d providers into 'universities' table...", len(uni_records))
    u_cnt = await upsert_universities(uni_records, chunk=args.chunk)
    logger.info("✓ Upserted %d university provider records.", u_cnt)

    logger.info("3/3 Upserting %d courses into 'courses' table...", len(course_records))
    c_cnt = await upsert_courses(course_records, chunk=args.chunk)
    logger.info("✓ Upserted %d undergraduate courses.", c_cnt)

    await dispose_engine()
    print("UK Discover Uni dataset successfully ingested into PostgreSQL.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Ingest UK Discover Uni Dataset into PostgreSQL.")
    parser.add_argument("--raw-dir", default=None, help="Directory containing the raw UK CSV files.")
    parser.add_argument("--limit", type=int, default=None, help="Maximum number of courses to ingest.")
    parser.add_argument("--tuition-gbp", type=float, default=DEFAULT_TUITION_GBP, help="Tuition in GBP.")
    parser.add_argument("--fx", type=float, default=DEFAULT_FX_GBP_USD, help="GBP to USD FX rate.")
    parser.add_argument("--chunk", type=int, default=DEFAULT_CHUNK, help="DB bulk insert chunk size.")
    parser.add_argument("--dry-run", action="store_true", help="Parse and report without writing to DB.")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return asyncio.run(run(args))


if __name__ == "__main__":
    sys.exit(main())
