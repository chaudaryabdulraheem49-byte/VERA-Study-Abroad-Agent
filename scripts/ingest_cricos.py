"""Load the official CRICOS register into Postgres.

CRICOS is the Australian government's register of providers and courses that
may enrol international students. It is the opposite of a crawled page: it is
authoritative, it is already structured, and it needs no LLM to read - so this
script makes no network request beyond the database connection.

    python scripts/ingest_cricos.py --dry-run
    python scripts/ingest_cricos.py

The register describes the whole post-school sector, not just universities, so
the two tables it fills serve different purposes:

    courses      the ~10k higher-education degrees the advisor can match on,
                 in the shape the Phase 2 hard filter already queries
    courses_raw  all 26k rows verbatim, so nothing from the register is lost
                 and a later decision to include, say, VET diplomas needs no
                 re-import

Fees are published in AUD. Both the AUD figure and the converted USD one are
stored: a converted number that cannot be traced back to its source is a
number nobody can check.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
import zipfile
from pathlib import Path
from typing import Any, Final

import pandas as pd
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.phase2.db import (  # noqa: E402
    Course,
    University,
    dispose_engine,
    get_engine,
    init_schema,
)

logger = logging.getLogger("ingest_cricos")

DEFAULT_ZIP: Final = REPO_ROOT / "cricos-providers-courses-and-locations.zip"
INSTITUTIONS_CSV: Final = "CRICOS Institutions.csv"
COURSES_CSV: Final = "CRICOS Courses.csv"

# AUD -> USD. Deliberately a parameter with a fixed default rather than a live
# lookup: a rate that moves between runs makes two imports of the same register
# disagree, and these figures are ranking inputs, not quoted prices.
DEFAULT_FX_AUD_USD: Final = 0.67

# The register uses the Australian Qualifications Framework, which has twenty
# levels. The advisor matches on three, so only the higher-education awards map
# - and the register's own wording is kept in `course_level_raw` either way.
#
# Graduate Certificates and Graduate Diplomas are postgraduate but are not
# Master's degrees, and calling them one would misdescribe the award a student
# would graduate with. They stay in courses_raw until there is somewhere honest
# to put them.
DEGREE_LEVEL_MAP: Final[dict[str, str]] = {
    "Bachelor Degree": "Bachelors",
    "Bachelor Honours Degree": "Bachelors",
    "Associate Degree": "Bachelors",
    "Masters Degree (Coursework)": "Masters",
    "Masters Degree (Research)": "Masters",
    "Masters Degree (Extended)": "Masters",
    "Doctoral Degree": "PhD",
}

CHUNK: Final = 1_000


# --------------------------------------------------------------------------- #
# Extract
# --------------------------------------------------------------------------- #


def extract(zip_path: Path, into: Path) -> Path:
    """Unzip the register, returning the directory holding the CSVs."""
    if not zip_path.is_file():
        raise FileNotFoundError(f"No CRICOS archive at {zip_path}")

    into.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        names = archive.namelist()
        missing = [n for n in (INSTITUTIONS_CSV, COURSES_CSV) if n not in names]
        if missing:
            raise ValueError(
                f"{zip_path.name} does not contain {missing}. Found: {names}"
            )
        archive.extractall(into)
    logger.info("Extracted %s to %s", zip_path.name, into)
    return into


# --------------------------------------------------------------------------- #
# Clean
# --------------------------------------------------------------------------- #


def _money(series: pd.Series) -> pd.Series:
    """`$13,450.00` -> `13450.0`. Anything unparseable becomes NaN, not zero."""
    return pd.to_numeric(
        series.astype("string").str.replace(r"[^0-9.]", "", regex=True),
        errors="coerce",
    )


def _int(series: pd.Series) -> pd.Series:
    """`2,610` -> `2610`. Kept nullable so a missing value stays missing."""
    return pd.to_numeric(
        series.astype("string").str.replace(r"[^0-9]", "", regex=True),
        errors="coerce",
    ).astype("Int64")


def load_institutions(csv_dir: Path) -> pd.DataFrame:
    frame = pd.read_csv(
        csv_dir / INSTITUTIONS_CSV, dtype=str, encoding="utf-8-sig", skip_blank_lines=True
    )
    frame = frame[frame["CRICOS Provider Code"].notna()].copy()

    out = pd.DataFrame(
        {
            "university_id": frame["CRICOS Provider Code"].str.strip(),
            "institution_name": frame["Institution Name"].str.strip(),
            "trading_name": frame["Trading Name"],
            "institution_type": frame["Institution Type"],
            "institution_capacity": _int(frame["Institution Capacity"]),
            "website": frame["Website"],
            "city": frame["Postal Address City"],
            "state": frame["Postal Address State"],
            "postcode": frame["Postal Address Postcode"],
            "country": "Australia",
        }
    )
    # One provider code, one row. A duplicate code in the source would silently
    # overwrite on upsert, so it is collapsed here where it can be counted.
    before = len(out)
    out = out.drop_duplicates(subset="university_id", keep="first")
    if before != len(out):
        logger.warning("Dropped %d duplicate provider code(s)", before - len(out))
    return out


def load_courses(csv_dir: Path, fx: float) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Return (all rows cleaned, the subset the advisor can match on)."""
    frame = pd.read_csv(csv_dir / COURSES_CSV, dtype=str, encoding="utf-8-sig")
    frame = frame[frame["CRICOS Provider Code"].notna()].copy()

    # An expired registration must not be recommended to anyone.
    expired = (frame["Expired"].str.strip().str.lower() == "yes").sum()
    frame = frame[frame["Expired"].str.strip().str.lower() != "yes"].copy()
    logger.info("Skipped %d expired course registration(s)", expired)

    frame["tuition_fee_aud"] = _money(frame["Estimated Total Course Cost"])
    frame["tuition_fee_usd"] = (frame["tuition_fee_aud"] * fx).round(2)
    frame["duration_weeks"] = _int(frame["Duration (Weeks)"])
    frame["degree_level"] = frame["Course Level"].str.strip().map(DEGREE_LEVEL_MAP)
    frame["syllabus_description"] = frame.apply(_describe, axis=1)

    degrees = frame[
        frame["degree_level"].notna() & frame["tuition_fee_aud"].notna()
    ].copy()

    # `(university_name, course_title)` is the courses table's natural key, and
    # the register lists the same award several times when it runs at several
    # campuses. Collapsing here, cheapest first, keeps the count honest instead
    # of letting the upsert quietly overwrite.
    before = len(degrees)
    degrees = degrees.sort_values("tuition_fee_aud").drop_duplicates(
        subset=["Institution Name", "Course Name"], keep="first"
    )
    logger.info(
        "Collapsed %d duplicate (provider, course) pairing(s)", before - len(degrees)
    )
    return frame, degrees


def _describe(row: pd.Series) -> str:
    """Compose the text that stands in for a syllabus.

    The register carries no prose - it is a legal listing, not a prospectus -
    so the closest thing to a subject description is its Field of Education
    classification. That is what makes these rows findable by subject at all,
    and it is thinner than a real course page.
    """
    fields = [
        row.get("Field of Education 1 Broad Field"),
        row.get("Field of Education 1 Narrow Field"),
        row.get("Field of Education 1 Detailed Field"),
        row.get("Field of Education 2 Detailed Field"),
    ]
    # The register prefixes each with its numeric code ("0909 - Law"); the
    # number carries no meaning for an embedding, so it is dropped.
    subjects = [
        str(value).split(" - ", 1)[-1].strip()
        for value in fields
        if isinstance(value, str) and value.strip()
    ]
    seen: list[str] = []
    for subject in subjects:
        if subject.lower() not in {s.lower() for s in seen}:
            seen.append(subject)

    parts = [
        str(row.get("Course Name", "")).strip(),
        f"({row.get('Course Level')})" if row.get("Course Level") else "",
        "at",
        str(row.get("Institution Name", "")).strip(),
        "in Australia.",
    ]
    if seen:
        parts.append("Field of education: " + "; ".join(seen) + ".")
    if pd.notna(row.get("duration_weeks")):
        parts.append(f"Duration {int(row['duration_weeks'])} weeks.")
    return " ".join(part for part in parts if part)


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #


def _rows(frame: pd.DataFrame) -> list[dict[str, Any]]:
    """DataFrame -> plain dicts with real None, which asyncpg requires."""
    return [
        {k: (None if pd.isna(v) else v) for k, v in record.items()}
        for record in frame.to_dict(orient="records")
    ]


async def upsert_universities(frame: pd.DataFrame) -> int:
    engine = get_engine()
    records = _rows(frame)
    written = 0
    async with engine.begin() as connection:
        for start in range(0, len(records), CHUNK):
            batch = records[start : start + CHUNK]
            statement = insert(University).values(batch)
            statement = statement.on_conflict_do_update(
                index_elements=["university_id"],
                set_={
                    column: statement.excluded[column]
                    for column in batch[0]
                    if column != "university_id"
                },
            )
            await connection.execute(statement)
            written += len(batch)
    return written


async def upsert_courses(frame: pd.DataFrame) -> int:
    engine = get_engine()
    payload = pd.DataFrame(
        {
            "course_title": frame["Course Name"].str.strip().str.slice(0, 300),
            "university_name": frame["Institution Name"].str.strip().str.slice(0, 300),
            "university_id": frame["CRICOS Provider Code"].str.strip(),
            "external_course_code": frame["CRICOS Course Code"].str.strip(),
            "country": "Australia",
            "degree_level": frame["degree_level"],
            "course_level_raw": frame["Course Level"].str.slice(0, 60),
            # Carried onto the main table, not just the staging one, so a
            # facet or a relaxed filter can group by discipline without a join.
            "field_broad": frame["Field of Education 1 Broad Field"].str.slice(0, 120),
            "field_narrow": frame["Field of Education 1 Narrow Field"].str.slice(0, 160),
            "field_detailed": frame[
                "Field of Education 1 Detailed Field"
            ].str.slice(0, 200),
            "duration_weeks": frame["duration_weeks"],
            "tuition_fee_aud": frame["tuition_fee_aud"],
            "tuition_fee_amount": frame["tuition_fee_aud"],
            "currency": "AUD",
            "tuition_fee_usd": frame["tuition_fee_usd"],
            # The register states no entry requirements. NULL says exactly
            # that; zero said "this course requires nothing", and a default
            # would say something the register does not. Measured on this
            # index, defaulting to 60% / IELTS 6.5 takes a student with IELTS
            # 6.0 from 3,795 eligible Australian Master's programmes to none.
            "min_gpa_percent": None,
            "min_ielts_score": None,
            # Nor does it publish intakes or closing dates. Saying so is
            # useful; inventing "Feb 2027 - Rolling" is something a student
            # would plan travel and money around.
            "deadline_date": None,
            "deadline_type": "not_published",
            "intakes": None,
            # Australia grants post-study work rights to graduates of
            # CRICOS-registered higher education awards, which is exactly this
            # subset - so it is a fact about the register, not a guess.
            "post_study_work_eligible": True,
            "syllabus_description": frame["syllabus_description"],
            "source_url": "https://cricos.education.gov.au/",
        }
    )

    records = _rows(payload)
    written = 0
    async with engine.begin() as connection:
        for start in range(0, len(records), CHUNK):
            batch = records[start : start + CHUNK]
            statement = insert(Course).values(batch)
            statement = statement.on_conflict_do_update(
                constraint="uq_courses_university_title",
                set_={
                    column: statement.excluded[column]
                    for column in batch[0]
                    # course_id is assigned on first insert and is the key the
                    # Qdrant point is stored under; changing it would orphan
                    # the vector.
                    if column not in {"course_id", "university_name", "course_title"}
                },
            )
            await connection.execute(statement)
            written += len(batch)
    return written


RAW_DDL: Final = """
CREATE TABLE IF NOT EXISTS courses_raw (
    external_course_code  VARCHAR(30) PRIMARY KEY,
    university_id         VARCHAR(20),
    institution_name      TEXT,
    course_title          TEXT,
    course_level_raw      VARCHAR(60),
    degree_level          VARCHAR(20),
    field_broad           TEXT,
    field_narrow          TEXT,
    field_detailed        TEXT,
    course_language       TEXT,
    duration_weeks        INTEGER,
    tuition_fee_aud       DOUBLE PRECISION,
    tuition_fee_usd       DOUBLE PRECISION,
    country               VARCHAR(100) DEFAULT 'Australia'
)
"""


async def upsert_raw(frame: pd.DataFrame) -> int:
    """Keep every register row, including the ones the advisor cannot match."""
    engine = get_engine()
    payload = pd.DataFrame(
        {
            "external_course_code": frame["CRICOS Course Code"].str.strip(),
            "university_id": frame["CRICOS Provider Code"].str.strip(),
            "institution_name": frame["Institution Name"],
            "course_title": frame["Course Name"],
            "course_level_raw": frame["Course Level"].str.slice(0, 60),
            "degree_level": frame["degree_level"],
            "field_broad": frame["Field of Education 1 Broad Field"],
            "field_narrow": frame["Field of Education 1 Narrow Field"],
            "field_detailed": frame["Field of Education 1 Detailed Field"],
            "course_language": frame["Course Language"],
            "duration_weeks": frame["duration_weeks"],
            "tuition_fee_aud": frame["tuition_fee_aud"],
            "tuition_fee_usd": frame["tuition_fee_usd"],
            "country": "Australia",
        }
    ).drop_duplicates(subset="external_course_code", keep="first")

    records = _rows(payload)
    written = 0
    async with engine.begin() as connection:
        await connection.execute(text(RAW_DDL))
        for start in range(0, len(records), CHUNK):
            batch = records[start : start + CHUNK]
            statement = text(
                "INSERT INTO courses_raw ("
                "external_course_code, university_id, institution_name, course_title,"
                "course_level_raw, degree_level, field_broad, field_narrow,"
                "field_detailed, course_language, duration_weeks, tuition_fee_aud,"
                "tuition_fee_usd, country) VALUES ("
                ":external_course_code, :university_id, :institution_name,"
                ":course_title, :course_level_raw, :degree_level, :field_broad,"
                ":field_narrow, :field_detailed, :course_language, :duration_weeks,"
                ":tuition_fee_aud, :tuition_fee_usd, :country) "
                "ON CONFLICT (external_course_code) DO NOTHING"
            )
            await connection.execute(statement, batch)
            written += len(batch)
    return written


ASCED_BACKFILL: Final = """
UPDATE courses AS c
SET field_broad    = r.field_broad,
    field_narrow   = r.field_narrow,
    field_detailed = r.field_detailed
FROM courses_raw AS r
WHERE c.external_course_code = r.external_course_code
  AND (c.field_broad IS DISTINCT FROM r.field_broad
       OR c.field_narrow IS DISTINCT FROM r.field_narrow
       OR c.field_detailed IS DISTINCT FROM r.field_detailed)
"""


async def backfill_asced() -> int:
    """Copy the Field of Education across from the staging table.

    Rows loaded before these columns existed carry no classification, and a
    re-ingest to get it would be minutes of work for three strings that are
    already sitting in `courses_raw`. Joined on the CRICOS course code, which
    is the register's own identifier and unique in both tables.

    `IS DISTINCT FROM` rather than `IS NULL`: it also repairs a row whose
    classification changed in a later release, and touches nothing that is
    already correct.
    """
    engine = get_engine()
    async with engine.begin() as connection:
        result = await connection.execute(text(ASCED_BACKFILL))
        return result.rowcount or 0


async def count_rows() -> dict[str, int]:
    engine = get_engine()
    counts: dict[str, int] = {}
    async with engine.connect() as connection:
        for table, where in (
            ("universities", ""),
            ("courses", ""),
            ("courses", "WHERE country = 'Australia'"),
            ("courses_raw", ""),
        ):
            key = f"{table} {where}".strip()
            result = await connection.execute(text(f"SELECT count(*) FROM {table} {where}"))
            counts[key] = int(result.scalar_one())
    return counts


# --------------------------------------------------------------------------- #
# Entry point
# --------------------------------------------------------------------------- #


async def run(args: argparse.Namespace) -> int:
    csv_dir = extract(Path(args.zip), Path(args.extract_dir))

    institutions = load_institutions(csv_dir)
    all_courses, degrees = load_courses(csv_dir, args.fx)

    print(f"\nProviders          {len(institutions):>7,}")
    print(f"Course rows        {len(all_courses):>7,}  (expired already removed)")
    print(f"  higher-ed awards {len(degrees):>7,}  -> courses")
    print(f"  everything else  {len(all_courses) - len(degrees):>7,}  -> courses_raw only")
    print("\nLevels mapped into the advisor's three:")
    for level, count in degrees["Course Level"].value_counts().items():
        print(f"  {level:32} {count:>6,} -> {DEGREE_LEVEL_MAP[level]}")
    print(f"\nFX applied: 1 AUD = {args.fx} USD")
    fees = degrees["tuition_fee_aud"]
    print(
        f"Tuition AUD  min {fees.min():,.0f}  median {fees.median():,.0f}  "
        f"max {fees.max():,.0f}"
    )

    if args.dry_run:
        print("\nDry run - nothing written. Drop --dry-run to load.")
        print(degrees[["Institution Name", "Course Name", "degree_level",
                       "duration_weeks", "tuition_fee_aud", "tuition_fee_usd"]]
              .head(5).to_string(index=False))
        return 0

    await init_schema()
    universities_written = await upsert_universities(institutions)
    raw_written = await upsert_raw(all_courses)
    courses_written = await upsert_courses(degrees)
    classified = await backfill_asced()

    print(f"\nUpserted {universities_written:,} provider(s)")
    print(f"Upserted {raw_written:,} raw course row(s)")
    print(f"Upserted {courses_written:,} matchable course(s)")
    if classified:
        print(f"Classified {classified:,} course(s) from the register's ASCED fields")
    print("\nRow counts now in Postgres:")
    for label, count in (await count_rows()).items():
        print(f"  {label:34} {count:>7,}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--zip", default=str(DEFAULT_ZIP))
    parser.add_argument(
        "--extract-dir",
        default=str(REPO_ROOT / "data" / "cricos"),
        help="where the CSVs are unpacked",
    )
    parser.add_argument("--fx", type=float, default=DEFAULT_FX_AUD_USD)
    parser.add_argument("--dry-run", action="store_true")
    return parser


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args()
    try:
        return asyncio.run(_dispatch(args))
    except KeyboardInterrupt:
        return 130


async def _dispatch(args: argparse.Namespace) -> int:
    try:
        return await run(args)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    raise SystemExit(main())
