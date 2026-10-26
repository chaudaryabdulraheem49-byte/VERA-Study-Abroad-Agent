"""Ingest Pan-European university courses into PostgreSQL.

Loads modular program seed records for 260 accredited European universities across 13 countries,
computes USD conversions, and idempotently upserts them into PostgreSQL `courses` table:
  - Idempotent upsert via ON CONFLICT (university_name, course_title) DO UPDATE
  - Sets tuition_fee_eur, tuition_fee_amount, tuition_fee_usd
  - Populates ECTS durations, intakes, rolling deadlines, IELTS/GPA thresholds, and rich embedding syllabi

Usage:
    python scripts/ingest_europe_courses.py --dry-run
    python scripts/ingest_europe_courses.py
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Final

from sqlalchemy.dialects.postgresql import insert

REPO_ROOT: Final = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "backend"))

from app.services.phase2.db import (  # noqa: E402
    Course,
    dispose_engine,
    get_engine,
    init_schema,
)

logger = logging.getLogger("ingest_europe_courses")
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

DEFAULT_SEED_PATH: Final = REPO_ROOT / "data" / "europe" / "seed_courses.json"
DEFAULT_FX_EUR_USD: Final = 1.08
CHUNK: Final = 100


def load_seed_courses(path: Path) -> list[dict[str, Any]]:
    """Read the European seed courses JSON dataset from disk."""
    if not path.is_file():
        raise FileNotFoundError(f"Seed file not found at: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []


def prepare_course_records(
    seeds: list[dict[str, Any]], fx: float
) -> list[dict[str, Any]]:
    """Transform seed definitions into Course model dictionary payloads."""
    records: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()

    for item in seeds:
        title = (item.get("course_title") or item.get("course_name") or "").strip()
        uni_name = (item.get("university_name") or item.get("institution_name") or "").strip()
        degree_level = (item.get("degree_level") or "Masters").strip()
        country = (item.get("country") or "Germany").strip()

        key = (uni_name, title)
        if key in seen:
            continue
        seen.add(key)

        fee_eur = float(item.get("tuition_fee_eur") or item.get("tuition_fee") or item.get("tuition_fee_amount") or 0.0)
        fee_usd = round(fee_eur * fx, 2) if fee_eur > 0 else 0.0

        min_ielts = float(
            item.get("min_ielts_score")
            or item.get("min_ielts")
            or (6.5 if degree_level == "Masters" else 6.0)
        )
        min_gpa = float(
            item.get("min_gpa_percent")
            or item.get("min_gpa")
            or 65.0
        )

        intakes = item.get("intakes") or '["Winter (September/October)", "Summer (March/April)"]'
        if isinstance(intakes, list):
            intakes = json.dumps(intakes)

        deadline_type = item.get("deadline_type", "ESTIMATED_ROLLING")
        next_deadline = item.get("next_deadline") or ("2027-01-15" if degree_level == "Masters" else "2026-07-15")

        syllabus = item.get("syllabus_description")
        if not syllabus:
            syllabus = (
                f"{title} ({degree_level}) offered by {uni_name} in {country}. "
                f"Language of instruction: 100% taught in English. "
                f"Field of study: {item.get('field_broad', 'Higher Education')}."
            )

        uni_id = item.get("university_id")
        code = item.get("external_course_code") or f"EU-{country[:2].upper()}-{len(records)+1:05d}"

        records.append(
            {
                "course_title": title[:300],
                "university_name": uni_name[:300],
                "university_id": uni_id[:20] if uni_id else None,
                "external_course_code": code[:30],
                "country": country[:100],
                "degree_level": degree_level[:20],
                "tuition_fee_amount": fee_eur,
                "currency": "EUR",
                "tuition_fee_usd": fee_usd,
                "tuition_fee_eur": fee_eur,
                "tuition_fee_cad": None,
                "tuition_fee_aud": None,
                "min_ielts_score": min_ielts,
                "min_gpa_percent": min_gpa,
                "deadline_date": next_deadline[:10],
                "deadline_type": deadline_type[:20],
                "next_deadline": next_deadline[:10],
                "intakes": intakes[:200],
                "post_study_work_eligible": True,
                "syllabus_description": syllabus,
                "source_url": item.get("source_url"),
                "duration_weeks": int(item.get("duration_weeks") or (156 if degree_level == "Bachelors" else 104)),
                "course_level_raw": item.get("course_level_raw", f"{degree_level} Degree")[:60],
                "field_broad": item.get("field_broad")[:120] if item.get("field_broad") else None,
                "field_narrow": item.get("field_narrow")[:160] if item.get("field_narrow") else None,
                "field_detailed": item.get("field_detailed")[:200] if item.get("field_detailed") else None,
            }
        )
    return records


async def upsert_courses(records: list[dict[str, Any]]) -> int:
    """Idempotently insert or update European courses in PostgreSQL."""
    engine = get_engine()
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
                    if column not in {"course_id", "university_name", "course_title"}
                },
            )
            await connection.execute(statement)
            written += len(batch)
    return written


def print_summary(records: list[dict[str, Any]]) -> None:
    """Print structured analytics of the European course catalog."""
    total = len(records)
    degrees = Counter(r["degree_level"] for r in records)
    countries = Counter(r["country"] for r in records)
    fields = Counter((r["field_broad"] or "Unclassified").split(" - ", 1)[-1] for r in records)

    tuition_free = sum(1 for r in records if r["tuition_fee_amount"] == 0)
    paid = total - tuition_free
    avg_paid_eur = sum(r["tuition_fee_amount"] for r in records if r["tuition_fee_amount"] > 0) / paid if paid else 0

    print("\n" + "=" * 68)
    print(" EUROPEAN COURSE CATALOG INGESTION SUMMARY")
    print("=" * 68)
    print(f"Total Programs Processed:       {total:,}")
    print(f"Tuition-Free Programs (0 EUR):  {tuition_free:,} ({100*tuition_free/total:.1f}%)")
    print(f"Fee-Paying Programs:            {paid:,} (avg €{avg_paid_eur:,.0f}/year)")
    print(f"Bachelors Degrees:              {degrees.get('Bachelors', 0):,}")
    print(f"Masters Degrees:                {degrees.get('Masters', 0):,}")

    print("\nPrograms by Country (13 Nations):")
    for country, count in countries.most_common():
        pct = 100.0 * count / total
        print(f"  {country:<18} {count:>5,} programs ({pct:5.1f}%)")

    print("\nPrograms by Broad Academic Cluster:")
    for field, count in fields.most_common():
        pct = 100.0 * count / total
        print(f"  {field:<36} {count:>5,} ({pct:5.1f}%)")
    print("=" * 68 + "\n")


async def run(args: argparse.Namespace) -> int:
    logger.info("Initializing schema...")
    await init_schema()

    logger.info(f"Loading European seed courses from {args.seed_file}...")
    seeds = load_seed_courses(args.seed_file)
    logger.info(f"Loaded {len(seeds)} raw course seeds.")

    records = prepare_course_records(seeds, fx=args.fx)
    print_summary(records)

    if args.dry_run:
        logger.info("Dry-run requested; skipping database writes.")
        return 0

    logger.info(f"Upserting {len(records)} European courses into PostgreSQL...")
    written = await upsert_courses(records)
    logger.info(f"Successfully upserted {written} courses into the database.")
    return 0


async def _dispatch(args: argparse.Namespace) -> int:
    try:
        return await run(args)
    finally:
        await dispose_engine()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed-file", type=Path, default=DEFAULT_SEED_PATH)
    parser.add_argument("--fx", type=float, default=DEFAULT_FX_EUR_USD, help="EUR to USD exchange rate")
    parser.add_argument("--dry-run", action="store_true", help="Parse and summarize without writing to DB")
    args = parser.parse_args()
    return asyncio.run(_dispatch(args))


if __name__ == "__main__":
    raise SystemExit(main())
