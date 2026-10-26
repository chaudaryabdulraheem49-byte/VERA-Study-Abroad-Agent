"""Ingest Canadian university courses into PostgreSQL.

Loads modular program seed records for top Canadian DLIs across STEM, Business,
and Arts, computes USD exchange conversions, and upserts them into PostgreSQL:
  - `courses` table: Hard filter-ready higher education records

Usage:
    python scripts/ingest_canada_courses.py --dry-run
    python scripts/ingest_canada_courses.py
    python scripts/ingest_canada_courses.py --fx 0.74
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

logger = logging.getLogger("ingest_canada_courses")

DEFAULT_SEED_PATH: Final = REPO_ROOT / "data" / "canada" / "seed_courses.json"
DEFAULT_FX_CAD_USD: Final = 0.74
CHUNK: Final = 100


def load_seed_courses(path: Path) -> list[dict[str, Any]]:
    """Read the seed courses JSON dataset from disk."""
    if not path.is_file():
        raise FileNotFoundError(f"Seed file not found at: {path}")
    raw = json.loads(path.read_text(encoding="utf-8"))
    return raw if isinstance(raw, list) else []


def prepare_course_records(
    seeds: list[dict[str, Any]], fx: float
) -> list[dict[str, Any]]:
    """Transform seed definitions into Course model dictionary payloads."""
    records: list[dict[str, Any]] = []
    for item in seeds:
        title = (item.get("course_title") or item.get("course_name") or "").strip()
        uni_name = (item.get("university_name") or item.get("institution_name") or "").strip()
        degree_level = item.get("degree_level", "Masters").strip()

        fee_cad = float(item.get("tuition_fee_cad") or item.get("tuition_fee") or 40000.0)
        fee_usd = round(fee_cad * fx, 2)

        # Default criteria according to spec
        min_ielts = float(
            item.get("min_ielts_score")
            or item.get("min_ielts")
            or (6.5 if degree_level == "Masters" else 6.0)
        )
        min_gpa = float(
            item.get("min_gpa_percent")
            or item.get("min_gpa")
            or (60.0 if degree_level == "Masters" else 55.0)
        )
        intakes = item.get("intakes") or '["September", "January"]'
        if isinstance(intakes, list):
            intakes = json.dumps(intakes)

        deadline_type = item.get("deadline_type", "ESTIMATED_ROLLING")
        next_deadline = item.get("next_deadline", "2027-01-15")

        syllabus = item.get("syllabus_description")
        if not syllabus:
            syllabus = (
                f"{title} ({degree_level}) program offered by {uni_name} in Canada. "
                f"Field of study: {item.get('field_broad', 'Higher Education')}."
            )

        uni_id = item.get("university_id") or item.get("dli_number")
        records.append(
            {
                "course_title": title[:300],
                "university_name": uni_name[:300],
                "university_id": uni_id,
                "external_course_code": item.get("external_course_code", f"CAD-{title[:10]}")[:30],
                "country": "Canada",
                "degree_level": degree_level[:20],
                "tuition_fee_amount": fee_cad,
                "currency": "CAD",
                "tuition_fee_usd": fee_usd,
                "tuition_fee_cad": fee_cad,
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
                "duration_weeks": int(item.get("duration_weeks", 208 if degree_level == "Bachelors" else 104)),
                "course_level_raw": item.get("course_level_raw", f"{degree_level} Degree")[:60],
                "field_broad": item.get("field_broad")[:120] if item.get("field_broad") else None,
                "field_narrow": item.get("field_narrow")[:160] if item.get("field_narrow") else None,
                "field_detailed": item.get("field_detailed")[:200] if item.get("field_detailed") else None,
            }
        )
    return records


async def upsert_courses(records: list[dict[str, Any]]) -> int:
    """Idempotently insert or update Canadian courses in PostgreSQL."""
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
    """Print structured analytics of the Canadian course catalog."""
    total = len(records)
    degrees = Counter(r["degree_level"] for r in records)
    unis = Counter(r["university_name"] for r in records)
    fields = Counter((r["field_broad"] or "Unclassified").split(" - ", 1)[-1] for r in records)

    avg_cad = sum(r["tuition_fee_amount"] for r in records) / total if total else 0
    avg_usd = sum(r["tuition_fee_usd"] for r in records) / total if total else 0

    print("\n" + "=" * 65)
    print(" CANADIAN COURSES INGESTION SUMMARY")
    print("=" * 65)
    print(f"Total Programs:          {total:,}")
    print(f"Average Annual Tuition:  ${avg_cad:,.0f} CAD (~${avg_usd:,.0f} USD)")

    print("\nBy Degree Level:")
    for deg, count in degrees.items():
        print(f"  {deg:<28} {count:>4,}  ({count / total * 100:5.1f}%)")

    print("\nBy Institution:")
    for uni, count in sorted(unis.items(), key=lambda x: x[1], reverse=True):
        print(f"  {uni:<38} {count:>4,} program(s)")

    print("\nBy Discipline Field:")
    for fld, count in sorted(fields.items(), key=lambda x: x[1], reverse=True):
        print(f"  {fld:<38} {count:>4,} program(s)")
    print("=" * 65 + "\n")


async def run(args: argparse.Namespace) -> int:
    seed_file = Path(args.seed_file)
    seeds = load_seed_courses(seed_file)
    if not seeds:
        logger.error("No seed courses found in %s", seed_file)
        return 1

    records = prepare_course_records(seeds, fx=args.fx)
    print_summary(records)

    if args.dry_run:
        print("Dry run requested: no courses written to PostgreSQL.")
        return 0

    await init_schema()
    written = await upsert_courses(records)
    print(f"Successfully upserted {written:,} Canadian courses into PostgreSQL.")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--seed-file",
        default=str(DEFAULT_SEED_PATH),
        help="Path to Canadian seed courses JSON file",
    )
    parser.add_argument(
        "--fx",
        type=float,
        default=DEFAULT_FX_CAD_USD,
        help="CAD -> USD exchange rate (default: 0.74)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Parse and summarize without writing to DB")
    return parser


async def _dispatch(args: argparse.Namespace) -> int:
    try:
        return await run(args)
    finally:
        await dispose_engine()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    args = build_parser().parse_args()
    try:
        return asyncio.run(_dispatch(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
