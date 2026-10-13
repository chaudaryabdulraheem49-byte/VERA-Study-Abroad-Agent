"""Command line entry point for the Phase 2 pipeline.

    python -m app.services.phase2.pipeline init
    python -m app.services.phase2.pipeline ingest <url> [<url> ...]
    python -m app.services.phase2.pipeline import courses.csv [--dry-run]
    python -m app.services.phase2.pipeline status
    python -m app.services.phase2.pipeline search "machine learning" \
        --budget 25000 --ielts 7 --country Germany --country Canada

Thin by design: argument parsing and printing only, so the services stay
importable from the API layer without dragging CLI concerns along.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

from ...config import get_settings
from .crawler_service import extract_courses
from .dataset_import import load_dataset
from .db import dispose_engine, init_schema
from .hybrid_search_service import search_courses
from .ingestion_service import (
    close_qdrant_client,
    ensure_collection,
    get_qdrant_client,
    ingest_many,
)
from .schemas import SearchConstraints

logger = logging.getLogger(__name__)


async def cmd_init(recreate: bool = False) -> int:
    """Create the Postgres table and the Qdrant collection."""
    await init_schema()
    await ensure_collection(get_qdrant_client(), recreate=recreate)
    print("Postgres schema and Qdrant collection are ready.")
    return 0


async def cmd_ingest(urls: list[str], concurrency: int) -> int:
    print(f"Crawling {len(urls)} page(s)...")
    courses, crawl_failures = await extract_courses(urls, concurrency=concurrency)

    for url, reason in crawl_failures.items():
        print(f"  crawl failed  {url}: {reason}", file=sys.stderr)
    if not courses:
        print("Nothing to ingest.", file=sys.stderr)
        return 1

    stored, ingest_failures = await ingest_many(courses)
    for key, reason in ingest_failures.items():
        print(f"  ingest failed {key}: {reason}", file=sys.stderr)

    for course in stored:
        print(
            f"  ok  {course.university_name} - {course.course_title} "
            f"(${course.tuition_fee_usd:,.0f}, IELTS {course.min_ielts_score}) "
            f"-> {course.course_id}"
        )
    print(f"Ingested {len(stored)}/{len(urls)} page(s).")
    return 0 if stored else 1


async def cmd_status() -> int:
    """Report index coverage: rows in Postgres versus vectors in Qdrant.

    The two stores can disagree without anything erroring. A course with a row
    but no vector passes the eligibility filter and is then dropped at the
    ranking step, so it is silently unreachable - which is exactly what a bulk
    import that writes rows directly produces. Nothing else in the pipeline
    makes that gap visible.
    """
    from sqlalchemy import func, select

    from .db import Course, session_scope

    async with session_scope() as session:
        total = (await session.execute(select(func.count(Course.course_id)))).scalar_one()
        by_country = (
            await session.execute(
                select(Course.country, func.count(Course.course_id))
                .group_by(Course.country)
                .order_by(func.count(Course.course_id).desc())
            )
        ).all()

    client = get_qdrant_client()
    await ensure_collection(client)
    info = await client.get_collection(get_settings().qdrant_collection)
    vectors = info.points_count or 0

    print(f"Postgres rows   {total:>8,}")
    print(f"Qdrant vectors  {vectors:>8,}")

    missing = total - vectors
    print()
    if missing > 0:
        print(
            f"{missing:,} course(s) have no vector. They pass the eligibility "
            "filter and are then dropped at the ranking step, so a student can "
            "never be shown them."
        )
        print("Fix with: python scripts/backfill_embeddings.py")
    elif missing < 0:
        print(
            f"{-missing:,} vector(s) have no row. Harmless - they can never be "
            "returned, since results are read from Postgres - but they are dead "
            "weight in the collection."
        )
    else:
        print("Every course is searchable.")

    print()
    print("By country:")
    for country, count in by_country[:12]:
        print(f"  {country:24} {count:>7,}")
    return 0


async def cmd_import(args: argparse.Namespace) -> int:
    """Load courses from a dataset file. Makes no request to any website."""
    path = Path(args.path)
    if not path.is_file():
        print(f"No such file: {path}", file=sys.stderr)
        return 1

    overrides: dict[str, str] = {}
    if args.mapping:
        overrides = json.loads(Path(args.mapping).read_text(encoding="utf-8"))

    report = load_dataset(path, overrides=overrides)
    print(f"Read {report.total} row(s) from {path.name}.")
    if report.mapped:
        print("Column mapping:")
        for source, target in sorted(report.mapped.items(), key=lambda kv: kv[1]):
            print(f"  {target:26} <- {source}")
    print(report.summary())

    # Rejections are listed in full up to a point, then counted: a dataset with
    # a systematically wrong column produces one line per row, and burying the
    # mapping table under it helps nobody.
    for row, reason in report.rejected[:20]:
        print(f"  row {row}: {reason}", file=sys.stderr)
    if len(report.rejected) > 20:
        print(f"  ... and {len(report.rejected) - 20} more", file=sys.stderr)

    if not report.courses:
        print("Nothing to import.", file=sys.stderr)
        return 1

    if args.dry_run:
        print()
        print("Dry run - nothing was written. Drop --dry-run to import.")
        for course in report.courses[:5]:
            print(
                f"  {course.university_name} - {course.course_title} "
                f"({course.degree_level}, {course.country}, "
                f"{course.tuition_fee_amount:,.0f} {course.currency})"
            )
        if len(report.courses) > 5:
            print(f"  ... and {len(report.courses) - 5} more")
        return 0

    stored, failures = await ingest_many(report.courses)
    for key, reason in failures.items():
        print(f"  ingest failed {key}: {reason}", file=sys.stderr)
    print(f"Imported {len(stored)}/{report.total} row(s).")
    return 0 if stored else 1


async def cmd_search(args: argparse.Namespace) -> int:
    constraints = SearchConstraints(
        max_budget_usd=args.budget,
        student_ielts=args.ielts,
        student_gpa_percent=args.gpa,
        countries=args.country or [],
        degree_levels=args.degree or [],
        post_study_work_required=args.psw,
        deadline_after=args.deadline_after,
    )
    matches = await search_courses(args.query, constraints, top_k=args.top)

    if not matches:
        print("No course met those constraints.")
        return 0

    for rank, match in enumerate(matches, start=1):
        print(
            f"{rank:2}. [{match.similarity_score:.3f}] {match.course_title}\n"
            f"     {match.university_name}, {match.country} - {match.degree_level}\n"
            f"     ${match.tuition_fee_usd:,.0f} USD "
            f"({match.tuition_fee_amount:,.0f} {match.currency}) | "
            f"IELTS {match.min_ielts_score} | GPA {match.min_gpa_percent}% | "
            f"deadline {match.deadline_date or 'not stated'}"
        )
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="phase2", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)

    init = sub.add_parser(
        "init", help="create the Postgres table and Qdrant collection"
    )
    init.add_argument(
        "--recreate",
        action="store_true",
        help="drop and rebuild the Qdrant collection (discards all vectors)",
    )

    ingest = sub.add_parser("ingest", help="crawl course pages and store them")
    ingest.add_argument("urls", nargs="+")
    ingest.add_argument("--concurrency", type=int, default=4)

    sub.add_parser(
        "status", help="show index coverage (Postgres rows vs Qdrant vectors)"
    )

    load = sub.add_parser(
        "import",
        help="load courses from a CSV/JSON dataset (no crawling, no web requests)",
    )
    load.add_argument("path", help=".csv, .tsv, .json, .jsonl or .ndjson")
    load.add_argument(
        "--mapping",
        default=None,
        help='JSON file of {"schema_field": "Source Column"} for columns the '
        "importer cannot guess",
    )
    load.add_argument(
        "--dry-run",
        action="store_true",
        help="validate and show the mapping without writing anything",
    )

    search = sub.add_parser("search", help="run a hybrid search")
    search.add_argument("query")
    search.add_argument("--budget", type=float, default=None, help="max USD tuition")
    search.add_argument("--ielts", type=float, default=None, help="student's band")
    search.add_argument("--gpa", type=float, default=None, help="student's percent")
    search.add_argument("--country", action="append", help="repeatable")
    search.add_argument("--degree", action="append", help="Bachelors|Masters|PhD")
    search.add_argument("--psw", action="store_true", help="post-study work only")
    search.add_argument("--deadline-after", default=None, help="YYYY-MM-DD")
    search.add_argument("--top", type=int, default=None)
    return parser


async def _dispatch(args: argparse.Namespace) -> int:
    try:
        if args.command == "init":
            return await cmd_init(recreate=args.recreate)
        if args.command == "ingest":
            return await cmd_ingest(args.urls, args.concurrency)
        if args.command == "import":
            return await cmd_import(args)
        if args.command == "status":
            return await cmd_status()
        return await cmd_search(args)
    finally:
        await dispose_engine()
        await close_qdrant_client()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s %(name)s: %(message)s"
    )
    args = build_parser().parse_args()
    try:
        return asyncio.run(_dispatch(args))
    except KeyboardInterrupt:
        return 130
    except Exception as exc:  # noqa: BLE001 - CLI boundary
        print(f"error: {exc}", file=sys.stderr)
        if _looks_like_connection_refused(exc):
            # The raw OS error names neither service, which is the least
            # useful thing it could say when two are required.
            settings = get_settings()
            print(
                "\nNeither Postgres nor Qdrant answered. Both are needed:\n"
                f"  Postgres: {settings.database_url}\n"
                f"  Qdrant:   {settings.qdrant_url}\n"
                "Start them with `docker compose up -d` from the repo root.",
                file=sys.stderr,
            )
        return 1


def _looks_like_connection_refused(exc: BaseException) -> bool:
    text = str(exc).lower()
    return (
        isinstance(exc, (ConnectionError, OSError))
        or "refused" in text
        or "connect call failed" in text
        or "could not connect" in text
    )


if __name__ == "__main__":
    raise SystemExit(main())
